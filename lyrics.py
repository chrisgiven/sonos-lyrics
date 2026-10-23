import json
import os
import re
import sqlite3
import threading
import time
import unicodedata

import requests

_art_cache: dict = {}
_bio_cache: dict = {}
_LRCLIB_GET_URL = "https://lrclib.net/api/get"
_LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
_MB_URL = "https://musicbrainz.org/ws/2/release/"
_CAA_URL = "https://coverartarchive.org/release/"
_MB_HEADERS = {"User-Agent": "SonosLyrics/1.0 (home-assistant)"}
_WIKI_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
_LINE_RE = re.compile(r"\[(\d{2}):(\d{2})\.(\d{2,3})\]\s*(.*)")


def _parse_lrc(lrc_text: str) -> list[dict]:
    """Parse LRC format into [{time_ms, text}] sorted by time."""
    lines = []
    for line in lrc_text.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        minutes, seconds, centis, text = m.groups()
        # centis may be 2 or 3 digits; normalise to ms
        centis_int = int(centis)
        if len(centis) == 2:
            centis_int *= 10
        time_ms = (int(minutes) * 60 + int(seconds)) * 1000 + centis_int
        lines.append({"time_ms": time_ms, "text": text.strip()})
    return sorted(lines, key=lambda x: x["time_ms"])


def fetch_album_art(artist: str, album: str) -> str:
    """Look up album art from MusicBrainz + Cover Art Archive. Returns URL or ''."""
    if not artist and not album:
        return ""
    key = (artist.lower(), album.lower())
    if key in _art_cache:
        return _art_cache[key]

    try:
        query = f"artist:{artist} AND release:{album}" if album else f"artist:{artist}"
        resp = requests.get(
            _MB_URL,
            params={"query": query, "fmt": "json", "limit": 1},
            headers=_MB_HEADERS,
            timeout=5,
        )
        resp.raise_for_status()
        releases = resp.json().get("releases", [])
        if not releases:
            _art_cache[key] = ""
            return ""

        release_id = releases[0]["id"]
        art_resp = requests.get(
            f"{_CAA_URL}{release_id}",
            headers=_MB_HEADERS,
            timeout=5,
            allow_redirects=True,
        )
        art_resp.raise_for_status()
        images = art_resp.json().get("images", [])
        url = images[0]["thumbnails"].get("large", images[0].get("image", "")) if images else ""
        _art_cache[key] = url
        return url
    except Exception:
        _art_cache[key] = ""
        return ""


def _truncate_bio(text: str, max_sentences: int = 3) -> str:
    """Return up to max_sentences sentences from text."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return " ".join(parts[:max_sentences])


def fetch_artist_info(artist: str, fallback_art_url: str = "") -> dict:
    """Fetch a short bio and photo URL for an artist from Wikipedia. Returns {"bio": str, "image_url": str}."""
    if not artist:
        return {"bio": "", "image_url": fallback_art_url, "wiki_url": ""}
    key = artist.lower()
    if key in _bio_cache:
        return _bio_cache[key]

    result = {"bio": "", "image_url": "", "wiki_url": ""}
    try:
        resp = requests.get(
            _WIKI_URL + requests.utils.quote(artist),
            headers={**_MB_HEADERS, "Accept": "application/json"},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            extract = data.get("extract", "")
            if extract and data.get("type") != "disambiguation":
                result["bio"] = _truncate_bio(extract)
            thumb = data.get("thumbnail", {})
            result["image_url"] = thumb.get("source", "")
            result["wiki_url"] = data.get("content_urls", {}).get("desktop", {}).get("page", "")
    except Exception:
        pass

    if not result["image_url"]:
        result["image_url"] = fallback_art_url

    _bio_cache[key] = result
    return result


# ── Lyrics lookup ────────────────────────────────────────

# Misses are retried after this long; hits are kept forever.
MISS_TTL_S = 3600
# A synced match whose length differs by more than this is a different version
# (live, edit, remix) and its timings won't line up.
_SYNCED_MAX_DRIFT_S = 10

_VERSION_WORDS = (
    r"remaster(?:ed)?|live|mono|stereo|version|edit|mix|demo|single|deluxe|bonus"
    r"|acoustic|outtake|take|anniversary|instrumental|session|recording|explicit|clean"
)
_DASH_SUFFIX_RE = re.compile(rf"\s+-\s+[^-]*\b(?:{_VERSION_WORDS})\b.*$", re.I)
_BRACKET_RE = re.compile(rf"\s*[(\[][^)\]]*\b(?:{_VERSION_WORDS}|feat\.?|ft\.?|with)\b[^)\]]*[)\]]", re.I)
_FEAT_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s.*$", re.I)
_ARTIST_SPLIT_RE = re.compile(r"\s*(?:,|;|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|\s&\s|\sx\s)\s*", re.I)

_db_lock = threading.Lock()
_db: sqlite3.Connection | None = None
_db_path = os.environ.get(
    "LYRICS_CACHE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "lyrics.db"),
)


def clean_title(title: str) -> str:
    """Strip version tags: 'Song - Remastered 2011' / 'Song (Live) [feat. X]' → 'Song'."""
    cleaned = _DASH_SUFFIX_RE.sub("", title)
    cleaned = _BRACKET_RE.sub("", cleaned)
    cleaned = _FEAT_RE.sub("", cleaned)
    return cleaned.strip() or title.strip()


def primary_artist(artist: str) -> str:
    """'Daft Punk, Pharrell Williams' / 'Daft Punk feat. Pharrell' → 'Daft Punk'."""
    first = _ARTIST_SPLIT_RE.split(artist.strip(), maxsplit=1)[0].strip()
    return first or artist.strip()


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _empty() -> dict:
    return {"synced": [], "plain": "", "instrumental": False}


def _is_hit(result: dict) -> bool:
    return bool(result["synced"] or result["plain"] or result["instrumental"])


def _from_record(rec: dict) -> dict:
    synced = rec.get("syncedLyrics")
    return {
        "synced": _parse_lrc(synced) if synced else [],
        "plain": (rec.get("plainLyrics") or "").strip(),
        "instrumental": bool(rec.get("instrumental")),
    }


# ── Disk cache ──

def set_cache_path(path: str) -> None:
    """Point the cache at a different SQLite file (used by tests)."""
    global _db, _db_path
    with _db_lock:
        if _db is not None:
            _db.close()
        _db, _db_path = None, path


def _conn() -> sqlite3.Connection:
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(_db_path) or ".", exist_ok=True)
        _db = sqlite3.connect(_db_path, check_same_thread=False)
        _db.execute(
            "CREATE TABLE IF NOT EXISTS lyrics ("
            " key TEXT PRIMARY KEY, result TEXT NOT NULL,"
            " hit INTEGER NOT NULL, fetched_at REAL NOT NULL)"
        )
    return _db


def _key(artist: str, title: str) -> str:
    return f"{artist.strip().lower()}\x1f{title.strip().lower()}"


def get_cached_lyrics(artist: str, title: str) -> dict | None:
    """Return a cached result, or None if never fetched or the cached miss has expired."""
    try:
        with _db_lock:
            row = _conn().execute(
                "SELECT result, hit, fetched_at FROM lyrics WHERE key = ?", (_key(artist, title),)
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    result, hit, fetched_at = row
    if not hit and time.time() - fetched_at > MISS_TTL_S:
        return None
    return json.loads(result)


def _store(artist: str, title: str, result: dict) -> None:
    try:
        with _db_lock:
            db = _conn()
            db.execute(
                "INSERT OR REPLACE INTO lyrics (key, result, hit, fetched_at) VALUES (?, ?, ?, ?)",
                (_key(artist, title), json.dumps(result), int(_is_hit(result)), time.time()),
            )
            db.commit()
    except sqlite3.Error:
        pass


# ── LRCLIB ──

def _lrclib_get(artist: str, title: str, duration_s: int) -> dict | None:
    params = {"artist_name": artist, "track_name": title}
    if duration_s:
        params["duration"] = duration_s
    resp = requests.get(_LRCLIB_GET_URL, params=params, headers=_MB_HEADERS, timeout=10)
    # LRCLIB answers a miss with 404, or with 503 when its upstream fallback also misses.
    if resp.status_code in (404, 503):
        return None
    resp.raise_for_status()
    return resp.json()


def _lrclib_search(artist: str, title: str, duration_s: int) -> dict | None:
    # Structured search (track_name + artist_name) 503s on LRCLIB; free-text q works.
    # Unlike /get, a search miss is 200 []; a 503 here is LRCLIB being flaky, so retry
    # once and otherwise raise — fetch_lyrics treats that as an error and won't cache it.
    for attempt in range(2):
        resp = requests.get(_LRCLIB_SEARCH_URL, params={"q": f"{title} {artist}"},
                            headers=_MB_HEADERS, timeout=10)
        if resp.status_code != 503 or attempt:
            break
        time.sleep(1)
    resp.raise_for_status()
    return _best_match(resp.json() or [], artist, title, duration_s)


def _best_match(records: list[dict], artist: str, title: str, duration_s: int) -> dict | None:
    """Pick the record for this song: synced and close in length first, then plain lyrics."""
    want_title, want_artist = _norm(title), _norm(artist)
    best, best_score = None, None
    for rec in records:
        rec_title = _norm(clean_title(rec.get("trackName") or ""))
        rec_artist = _norm(rec.get("artistName") or "")
        if rec_title != want_title or want_artist not in rec_artist:
            continue
        drift = abs((rec.get("duration") or 0) - duration_s) if duration_s else 0
        if rec.get("syncedLyrics") and drift <= _SYNCED_MAX_DRIFT_S:
            score = (0, drift)
        elif rec.get("plainLyrics") or rec.get("syncedLyrics") or rec.get("instrumental"):
            # Too far off in length for its timings, but the words are still the song's.
            rec = {**rec, "syncedLyrics": None, "plainLyrics": rec.get("plainLyrics")
                   or _strip_timestamps(rec.get("syncedLyrics") or "")}
            score = (1, drift)
        else:
            continue
        if best_score is None or score < best_score:
            best, best_score = rec, score
    return best


def _strip_timestamps(lrc: str) -> str:
    return "\n".join(line["text"] for line in _parse_lrc(lrc))


def fetch_lyrics(artist: str, title: str, duration_ms: int = 0) -> dict:
    """Find lyrics for a track. Returns {"synced": [{time_ms, text}], "plain": str, "instrumental": bool}.

    Tries the exact title, then the title with version tags stripped, then a
    free-text search. Hits are cached on disk forever, misses for MISS_TTL_S;
    network errors are not cached so the next play retries.
    """
    if not title:
        return _empty()
    cached = get_cached_lyrics(artist, title)
    if cached is not None:
        return cached

    duration_s = round(duration_ms / 1000) if duration_ms else 0
    short_title, short_artist = clean_title(title), primary_artist(artist)
    attempts = [lambda: _lrclib_get(artist, title, duration_s)]
    if (short_artist, short_title) != (artist, title):
        attempts.append(lambda: _lrclib_get(short_artist, short_title, duration_s))
    attempts.append(lambda: _lrclib_search(short_artist, short_title, duration_s))

    result, errored = _empty(), False
    for attempt in attempts:
        try:
            rec = attempt()
        except Exception:
            errored = True
            continue
        if rec:
            candidate = _from_record(rec)
            if candidate["synced"]:
                result = candidate
                break
            if _is_hit(candidate) and not _is_hit(result):
                result = candidate  # keep looking for a synced version

    if _is_hit(result) or not errored:
        _store(artist, title, result)
    return result

import re
import requests

_cache: dict = {}
_art_cache: dict = {}
_bio_cache: dict = {}
_LRCLIB_URL = "https://lrclib.net/api/get"
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
    import re as _re
    parts = _re.split(r'(?<=[.!?])\s+', text.strip())
    return " ".join(parts[:max_sentences])


def fetch_artist_info(artist: str, fallback_art_url: str = "") -> dict:
    """Fetch a short bio and photo URL for an artist from Wikipedia. Returns {"bio": str, "image_url": str}."""
    if not artist:
        return {"bio": "", "image_url": fallback_art_url}
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


def fetch_lyrics(artist: str, title: str) -> list[dict]:
    """Fetch synced lyrics from LRCLIB. Returns [] if unavailable."""
    key = (artist.lower(), title.lower())
    if key in _cache:
        return _cache[key]

    try:
        resp = requests.get(
            _LRCLIB_URL,
            params={"artist_name": artist, "track_name": title},
            timeout=15,
        )
        if resp.status_code == 404:
            _cache[key] = []
            return []
        resp.raise_for_status()
        data = resp.json()
        synced = data.get("syncedLyrics")
        result = _parse_lrc(synced) if synced else []
    except Exception:
        result = []

    _cache[key] = result
    return result

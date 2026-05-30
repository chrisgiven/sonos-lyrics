import re
import requests

_cache: dict = {}
_LRCLIB_URL = "https://lrclib.net/api/get"
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


def fetch_lyrics(artist: str, title: str) -> list[dict]:
    """Fetch synced lyrics from LRCLIB. Returns [] if unavailable."""
    key = (artist.lower(), title.lower())
    if key in _cache:
        return _cache[key]

    try:
        resp = requests.get(
            _LRCLIB_URL,
            params={"artist_name": artist, "track_name": title},
            timeout=5,
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

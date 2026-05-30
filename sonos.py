import requests
import xml.etree.ElementTree as ET


class SonosUnavailableError(Exception):
    pass


def _parse_reltime(reltime: str) -> int:
    """Convert H:MM:SS or M:SS to milliseconds."""
    parts = reltime.strip().split(":")
    parts = [int(p) for p in parts]
    if len(parts) == 3:
        h, m, s = parts
    else:
        h, m, s = 0, parts[0], parts[1]
    return (h * 3600 + m * 60 + s) * 1000


def get_current_track(ip: str) -> dict:
    """Poll Sonos trackinfo endpoint. Raises SonosUnavailableError on failure."""
    url = f"http://{ip}:1400/status/trackinfo"
    try:
        resp = requests.get(url, timeout=2)
        resp.raise_for_status()
    except Exception as e:
        raise SonosUnavailableError(str(e)) from e

    root = ET.fromstring(resp.text)
    return {
        "title": root.findtext("title", "").strip(),
        "artist": root.findtext("artist", "").strip(),
        "album": root.findtext("album", "").strip(),
        "position_ms": _parse_reltime(root.findtext("reltime", "0:00")),
    }

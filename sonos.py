import html
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

_SOAP_BODY = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
    ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    "<s:Body>"
    '<u:GetPositionInfo xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
    "<InstanceID>0</InstanceID>"
    "</u:GetPositionInfo>"
    "</s:Body>"
    "</s:Envelope>"
)
_SOAP_HEADERS = {
    "Content-Type": 'text/xml; charset="utf-8"',
    "SOAPAction": '"urn:schemas-upnp-org:service:AVTransport:1#GetPositionInfo"',
}
_STREAM_RE = re.compile(r"TITLE\s+(.+?)(?:\|ARTIST\s+(.+?))?(?:\|ALBUM\s+(.+?))?(?:\|TYPE.*)?$")


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


def _parse_metadata(raw_metadata: str) -> tuple[str, str, str]:
    """Extract (title, artist, album) from DIDL-Lite XML metadata string."""
    if not raw_metadata or raw_metadata == "NOT_IMPLEMENTED":
        return "", "", ""

    try:
        root = ET.fromstring(raw_metadata)
        ns = {
            "dc": "http://purl.org/dc/elements/1.1/",
            "upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/",
            "r": "urn:schemas-rinconnetworks-com:metadata-1-0/",
            "didl": "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/",
        }
        item = root.find("didl:item", ns)
        if item is None:
            return "", "", ""

        # Standard track fields (Apple Music, local library, etc.)
        title = (item.findtext("dc:title", "", ns) or "").strip()
        artist = (item.findtext("dc:creator", "", ns) or "").strip()
        album = (item.findtext("upnp:album", "", ns) or "").strip()

        if title:
            return title, artist, album

        # Radio/streaming fallback: r:streamContent pipe-delimited string
        stream = (item.findtext("r:streamContent", "", ns) or "").strip()
        if stream:
            m = _STREAM_RE.search(stream)
            if m:
                return (m.group(1) or "").strip(), (m.group(2) or "").strip(), (m.group(3) or "").strip()

    except ET.ParseError:
        pass

    return "", "", ""


def get_current_track(ip: str) -> dict:
    """Poll Sonos via UPnP SOAP. Raises SonosUnavailableError on failure."""
    url = f"http://{ip}:1400/MediaRenderer/AVTransport/Control"
    try:
        resp = requests.post(url, data=_SOAP_BODY, headers=_SOAP_HEADERS, timeout=2)
        resp.raise_for_status()
    except Exception as e:
        raise SonosUnavailableError(str(e)) from e

    try:
        root = ET.fromstring(resp.text)
        ns_soap = "http://schemas.xmlsoap.org/soap/envelope/"
        ns_avt = "urn:schemas-upnp-org:service:AVTransport:1"
        info = root.find(f"{{{ns_soap}}}Body/{{{ns_avt}}}GetPositionInfoResponse")
        if info is None:
            raise SonosUnavailableError("Unexpected SOAP response")

        raw_meta = info.findtext("TrackMetaData", "")
        reltime = info.findtext("RelTime", "0:00:00")
        title, artist, album = _parse_metadata(raw_meta)

        try:
            position_ms = _parse_reltime(reltime)
        except (ValueError, IndexError):
            position_ms = 0

        return {"title": title, "artist": artist, "album": album, "position_ms": position_ms}

    except SonosUnavailableError:
        raise
    except Exception as e:
        raise SonosUnavailableError(str(e)) from e


def find_playing(ips: list[str]) -> dict:
    """Poll all IPs in parallel and return the first one that's playing. Raises SonosUnavailableError if none are playing."""
    with ThreadPoolExecutor(max_workers=len(ips)) as pool:
        futures = {pool.submit(get_current_track, ip): ip for ip in ips}
        for future in as_completed(futures):
            try:
                track = future.result()
                if track["title"]:
                    return track
            except SonosUnavailableError:
                continue
    raise SonosUnavailableError("No playing speaker found")

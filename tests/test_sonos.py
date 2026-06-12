import html
import pytest
from unittest.mock import patch, Mock
from sonos import get_current_track, SonosUnavailableError, _parse_metadata


def _soap_response(title="Bohemian Rhapsody", artist="Queen", album="A Night at the Opera",
                   reltime="0:01:23", duration="3:32"):
    didl = (
        '&lt;DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"'
        ' xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"&gt;'
        '&lt;item id="-1" parentID="-1" restricted="true"&gt;'
        f'&lt;dc:title&gt;{title}&lt;/dc:title&gt;'
        f'&lt;dc:creator&gt;{artist}&lt;/dc:creator&gt;'
        f'&lt;upnp:album&gt;{album}&lt;/upnp:album&gt;'
        '&lt;/item&gt;&lt;/DIDL-Lite&gt;'
    )
    return f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:GetPositionInfoResponse xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <Track>1</Track>
      <TrackDuration>{duration}</TrackDuration>
      <TrackMetaData>{didl}</TrackMetaData>
      <RelTime>{reltime}</RelTime>
    </u:GetPositionInfoResponse>
  </s:Body>
</s:Envelope>"""


def test_get_current_track_parses_fields():
    with patch("sonos.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, text=_soap_response())
        track = get_current_track("192.168.1.10")
    assert track["title"] == "Bohemian Rhapsody"
    assert track["artist"] == "Queen"
    assert track["album"] == "A Night at the Opera"
    assert track["position_ms"] == 83000  # 1m23s


def test_get_current_track_raises_when_unreachable():
    import requests
    with patch("sonos.requests.post", side_effect=requests.exceptions.ConnectionError):
        with pytest.raises(SonosUnavailableError):
            get_current_track("192.168.1.10")


def test_reltime_parsing_no_hours():
    with patch("sonos.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, text=_soap_response(reltime="3:45"))
        track = get_current_track("192.168.1.10")
    assert track["position_ms"] == 225000  # 3m45s


def test_get_current_track_includes_duration_ms():
    with patch("sonos.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, text=_soap_response(duration="3:32"))
        track = get_current_track("192.168.1.10")
    assert track["duration_ms"] == 212000  # 3m32s


def test_get_current_track_duration_ms_zero_for_radio():
    with patch("sonos.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, text=_soap_response(duration="NOT_IMPLEMENTED"))
        track = get_current_track("192.168.1.10")
    assert track["duration_ms"] == 0


def test_parse_metadata_stream_content():
    """Radio/streaming fallback via r:streamContent pipe-delimited string."""
    raw = html.unescape(
        '&lt;DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/"'
        ' xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"&gt;'
        '&lt;item id="-1" parentID="-1" restricted="true"&gt;'
        '&lt;r:streamContent&gt;TYPE=SNG|TITLE Yesterday|ARTIST The Beatles|ALBUM Help!&lt;/r:streamContent&gt;'
        '&lt;/item&gt;&lt;/DIDL-Lite&gt;'
    )
    title, artist, album, _ = _parse_metadata(raw)
    assert title == "Yesterday"
    assert artist == "The Beatles"
    assert album == "Help!"

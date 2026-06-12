import html
import pytest
from unittest.mock import patch, Mock
from sonos import get_current_track, SonosUnavailableError, _parse_metadata, transport_command, get_volume, set_volume


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


def test_transport_command_play_sends_correct_soap():
    with patch("sonos.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, text="<ok/>")
        transport_command("192.168.1.10", "Play")
    call_kwargs = mock_post.call_args[1]
    assert "Play" in call_kwargs["headers"]["SOAPAction"]
    assert "<Speed>1</Speed>" in call_kwargs["data"]


def test_transport_command_pause_sends_correct_soap():
    with patch("sonos.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, text="<ok/>")
        transport_command("192.168.1.10", "Pause")
    assert "Pause" in mock_post.call_args[1]["headers"]["SOAPAction"]


def test_transport_command_raises_on_failure():
    import requests as req
    with patch("sonos.requests.post", side_effect=req.exceptions.ConnectionError):
        with pytest.raises(SonosUnavailableError):
            transport_command("192.168.1.10", "Play")


def _volume_response(volume: int = 65) -> str:
    return f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:GetVolumeResponse xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">
      <CurrentVolume>{volume}</CurrentVolume>
    </u:GetVolumeResponse>
  </s:Body>
</s:Envelope>"""


def test_get_volume_returns_integer():
    with patch("sonos.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, text=_volume_response(65))
        result = get_volume("192.168.1.10")
    assert result == 65


def test_get_volume_raises_on_failure():
    import requests as req
    with patch("sonos.requests.post", side_effect=req.exceptions.ConnectionError):
        with pytest.raises(SonosUnavailableError):
            get_volume("192.168.1.10")


def test_set_volume_sends_correct_level():
    with patch("sonos.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, text="<ok/>")
        set_volume("192.168.1.10", 42)
    call_kwargs = mock_post.call_args[1]
    assert "42" in call_kwargs["data"]
    assert "SetVolume" in call_kwargs["headers"]["SOAPAction"]


def test_set_volume_raises_on_failure():
    import requests as req
    with patch("sonos.requests.post", side_effect=req.exceptions.ConnectionError):
        with pytest.raises(SonosUnavailableError):
            set_volume("192.168.1.10", 50)


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

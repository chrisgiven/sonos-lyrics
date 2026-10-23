import html
import pytest
from unittest.mock import patch, Mock
from sonos import get_current_track, SonosUnavailableError, _parse_metadata, transport_command, get_volume, set_volume


def _soap_response(title="Bohemian Rhapsody", artist="Queen", album="A Night at the Opera",
                   reltime="0:01:23", duration="3:32", art=""):
    didl = (
        '&lt;DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"'
        ' xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"&gt;'
        '&lt;item id="-1" parentID="-1" restricted="true"&gt;'
        f'&lt;dc:title&gt;{title}&lt;/dc:title&gt;'
        f'&lt;dc:creator&gt;{artist}&lt;/dc:creator&gt;'
        f'&lt;upnp:album&gt;{album}&lt;/upnp:album&gt;'
        + (f'&lt;upnp:albumArtURI&gt;{html.escape(html.escape(art))}&lt;/upnp:albumArtURI&gt;' if art else '') +
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


# ── Grouping ──

from sonos import get_zone_group_state, join_group, leave_group, set_group_volume


def _zone_state_response():
    inner = (
        '<ZoneGroupState><ZoneGroups>'
        '<ZoneGroup Coordinator="RINCON_A" ID="RINCON_A:1">'
        '<ZoneGroupMember UUID="RINCON_A" Location="http://192.168.1.10:1400/xml/device_description.xml" ZoneName="Office"/>'
        '<ZoneGroupMember UUID="RINCON_B" Location="http://192.168.1.11:1400/xml/device_description.xml" ZoneName="Kitchen"/>'
        '</ZoneGroup>'
        '<ZoneGroup Coordinator="RINCON_C" ID="RINCON_C:1">'
        '<ZoneGroupMember UUID="RINCON_C" Location="http://192.168.1.12:1400/xml/device_description.xml" ZoneName="Den"/>'
        '</ZoneGroup>'
        '</ZoneGroups></ZoneGroupState>'
    )
    return f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:GetZoneGroupStateResponse xmlns:u="urn:schemas-upnp-org:service:ZoneGroupTopology:1">
      <ZoneGroupState>{html.escape(inner)}</ZoneGroupState>
    </u:GetZoneGroupStateResponse>
  </s:Body>
</s:Envelope>"""


def test_get_zone_group_state_maps_members_to_coordinator():
    with patch("sonos.requests.post", return_value=Mock(status_code=200, text=_zone_state_response(),
                                                         raise_for_status=Mock())):
        topo = get_zone_group_state("192.168.1.10")
    assert topo["192.168.1.11"]["coordinator_ip"] == "192.168.1.10"
    assert topo["192.168.1.10"]["members"] == ["192.168.1.10", "192.168.1.11"]
    assert topo["192.168.1.12"] == {"uid": "RINCON_C", "coordinator_ip": "192.168.1.12", "members": ["192.168.1.12"]}


def test_get_zone_group_state_returns_empty_on_failure():
    with patch("sonos.requests.post", side_effect=Exception("down")):
        assert get_zone_group_state("192.168.1.10") == {}


def test_join_group_points_member_at_coordinator_uid():
    desc = Mock(status_code=200, text="<root><UDN>uuid:RINCON_A01400</UDN></root>", raise_for_status=Mock())
    with patch("sonos.requests.get", return_value=desc), \
         patch("sonos.requests.post", return_value=Mock(raise_for_status=Mock())) as post:
        join_group("192.168.1.11", "192.168.1.10")
    url = post.call_args[0][0]
    assert url == "http://192.168.1.11:1400/MediaRenderer/AVTransport/Control"
    assert "<CurrentURI>x-rincon:RINCON_A01400</CurrentURI>" in post.call_args[1]["data"]


def test_leave_group_raises_when_speaker_unreachable():
    with patch("sonos.requests.post", side_effect=Exception("down")):
        with pytest.raises(SonosUnavailableError):
            leave_group("192.168.1.11")


def test_set_group_volume_targets_coordinator():
    with patch("sonos.requests.post", return_value=Mock(raise_for_status=Mock())) as post:
        set_group_volume("192.168.1.10", 30)
    assert post.call_args[0][0].endswith(":1400/MediaRenderer/GroupRenderingControl/Control")
    assert "<DesiredVolume>30</DesiredVolume>" in post.call_args[1]["data"]


def test_get_current_track_makes_relative_art_absolute():
    with patch("sonos.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, text=_soap_response(art="/getaa?s=1&u=x-sonos-http%3asong"))
        result = get_current_track("192.168.1.10")
    assert result["art_url"] == "http://192.168.1.10:1400/getaa?s=1&u=x-sonos-http%3asong"


def test_get_current_track_keeps_absolute_art():
    with patch("sonos.requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200, text=_soap_response(art="https://img.example/a.jpg"))
        result = get_current_track("192.168.1.10")
    assert result["art_url"] == "https://img.example/a.jpg"

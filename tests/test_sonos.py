import pytest
from unittest.mock import patch, Mock
from sonos import get_current_track, SonosUnavailableError

SAMPLE_XML = """<?xml version="1.0" ?>
<TrackInfo>
  <title>Bohemian Rhapsody</title>
  <artist>Queen</artist>
  <album>A Night at the Opera</album>
  <reltime>0:01:23</reltime>
  <duration>0:05:55</duration>
</TrackInfo>"""

def test_get_current_track_parses_fields():
    with patch("sonos.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, text=SAMPLE_XML)
        track = get_current_track("192.168.1.10")
    assert track["title"] == "Bohemian Rhapsody"
    assert track["artist"] == "Queen"
    assert track["album"] == "A Night at the Opera"
    assert track["position_ms"] == 83000  # 1m23s

def test_get_current_track_raises_when_unreachable():
    import requests
    with patch("sonos.requests.get", side_effect=requests.exceptions.ConnectionError):
        with pytest.raises(SonosUnavailableError):
            get_current_track("192.168.1.10")

def test_reltime_parsing_no_hours():
    with patch("sonos.requests.get") as mock_get:
        xml = SAMPLE_XML.replace("0:01:23", "3:45")
        mock_get.return_value = Mock(status_code=200, text=xml)
        track = get_current_track("192.168.1.10")
    assert track["position_ms"] == 225000  # 3m45s

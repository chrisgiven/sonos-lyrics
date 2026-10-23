import pytest
import json
from unittest.mock import patch, MagicMock
from server import create_app
from sonos import SonosUnavailableError


@pytest.fixture
def app():
    return create_app(sonos_ip="192.168.1.10")


@pytest.fixture
def client(app):
    return app.test_client()


def test_index_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_stream_content_type(client):
    with patch("server.get_current_track", side_effect=Exception("skip")):
        resp = client.get("/stream", headers={"Accept": "text/event-stream"})
    assert "text/event-stream" in resp.content_type


def test_stream_emits_waiting_when_sonos_down(client):
    from sonos import SonosUnavailableError
    with patch("server.get_current_track", side_effect=SonosUnavailableError("off")):
        with client.get("/stream", buffered=False) as resp:
            chunk = next(resp.response).decode()
    assert "waiting" in chunk


def _events(resp, n):
    out = []
    for raw in resp.response:
        chunk = raw.decode()
        if chunk.startswith(":"):
            continue
        event = chunk.split("event: ", 1)[1].split("\n", 1)[0]
        out.append((event, json.loads(chunk.split("data: ", 1)[1])))
        if len(out) == n:
            return out
    return out


LYRICS = {"synced": [{"time_ms": 1000, "text": "Yesterday"}], "plain": "Yesterday", "instrumental": False}
TRACK = {"title": "Yesterday", "artist": "Beatles", "album": "Help!", "position_ms": 0, "duration_ms": 125000}


def test_stream_sends_cached_lyrics_with_track_change(client):
    with patch("server.get_current_track", return_value=TRACK), \
         patch("server.get_cached_lyrics", return_value=LYRICS), \
         patch("server.fetch_lyrics") as fetch:
        with client.get("/stream", buffered=False) as resp:
            [(event, data)] = _events(resp, 1)
    assert event == "track_change"
    assert data["title"] == "Yesterday"
    assert data["lyrics"][0]["text"] == "Yesterday"
    assert data["plain_lyrics"] == "Yesterday"
    assert data["lyrics_pending"] is False
    fetch.assert_not_called()


def test_stream_fetches_uncached_lyrics_in_background(client):
    with patch("server.get_current_track", return_value=TRACK), \
         patch("server.get_cached_lyrics", return_value=None), \
         patch("server.fetch_lyrics", return_value=LYRICS) as fetch:
        with client.get("/stream", buffered=False) as resp:
            events = _events(resp, 2)
    track_change = next(d for e, d in events if e == "track_change")
    assert track_change["lyrics_pending"] is True
    assert track_change["lyrics"] == []
    lyrics_event = next(d for e, d in events if e == "lyrics")
    assert lyrics_event["title"] == "Yesterday"
    assert lyrics_event["lyrics"][0]["text"] == "Yesterday"
    fetch.assert_called_once_with("Beatles", "Yesterday", 125000)


def test_late_joiner_gets_current_track(app):
    with patch("server.get_current_track", return_value=TRACK), \
         patch("server.get_cached_lyrics", return_value=LYRICS):
        first, second = app.test_client(), app.test_client()
        with first.get("/stream", buffered=False) as r1:
            _events(r1, 1)
            with second.get("/stream", buffered=False) as r2:
                [(event, data)] = _events(r2, 1)
    assert event == "track_change"
    assert data["title"] == "Yesterday"


def test_control_play_calls_transport_command(client):
    with patch("server.transport_command") as mock_cmd:
        resp = client.post("/control?ip=192.168.1.10",
                           json={"action": "play"},
                           content_type="application/json")
    assert resp.status_code == 204
    mock_cmd.assert_called_once_with("192.168.1.10", "Play")


def test_control_returns_400_for_invalid_action(client):
    resp = client.post("/control?ip=192.168.1.10",
                       json={"action": "rewind"},
                       content_type="application/json")
    assert resp.status_code == 400


def test_control_returns_503_when_speaker_unavailable(client):
    with patch("server.transport_command", side_effect=SonosUnavailableError("off")):
        resp = client.post("/control?ip=192.168.1.10",
                           json={"action": "pause"},
                           content_type="application/json")
    assert resp.status_code == 503


def test_volume_sets_level(client):
    with patch("server.set_volume") as mock_vol:
        resp = client.post("/volume?ip=192.168.1.10",
                           json={"level": 42},
                           content_type="application/json")
    assert resp.status_code == 204
    mock_vol.assert_called_once_with("192.168.1.10", 42)


def test_volume_returns_400_for_out_of_range(client):
    resp = client.post("/volume?ip=192.168.1.10",
                       json={"level": 150},
                       content_type="application/json")
    assert resp.status_code == 400


def test_volume_returns_400_for_non_integer(client):
    resp = client.post("/volume?ip=192.168.1.10",
                       json={"level": "loud"},
                       content_type="application/json")
    assert resp.status_code == 400

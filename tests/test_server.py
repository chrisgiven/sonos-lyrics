import pytest
import json
from unittest.mock import patch, MagicMock
from server import create_app


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


def test_stream_emits_track_change_on_new_track(client):
    track = {"title": "Yesterday", "artist": "Beatles", "album": "Help!", "position_ms": 0}
    lyrics = [{"time_ms": 1000, "text": "Yesterday"}]
    with patch("server.get_current_track", return_value=track), \
         patch("server.fetch_lyrics", return_value=lyrics):
        with client.get("/stream", buffered=False) as resp:
            chunk = next(resp.response).decode()
    assert "track_change" in chunk
    data = json.loads(chunk.split("data: ", 1)[1])
    assert data["title"] == "Yesterday"
    assert data["lyrics"][0]["text"] == "Yesterday"

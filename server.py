import json
import logging
import queue
import threading
import time

from flask import Flask, Response, stream_with_context

from lyrics import fetch_lyrics
from sonos import SonosUnavailableError, find_playing, get_current_track


def create_app(sonos_ip: str, poll_interval: float = 1.0, initial_delay: float = 0.0) -> Flask:
    app = Flask(__name__, static_folder="static")

    # Shared state
    _state = {"track": None, "lyrics": []}
    _clients: list[queue.SimpleQueue] = []
    _lock = threading.Lock()
    _has_client = threading.Event()

    def _broadcast(event: str, data: dict):
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        with _lock:
            for q in list(_clients):
                q.put(payload)

    ips = [ip.strip() for ip in sonos_ip.split(",") if ip.strip()]
    _get_track = (lambda: find_playing(ips)) if len(ips) > 1 else (lambda: get_current_track(ips[0]))

    def _poll():
        if initial_delay:
            time.sleep(initial_delay)
        while True:
            # Wait until at least one client is connected before polling
            _has_client.wait()
            try:
                track = _get_track()
                prev = _state["track"]
                if prev is None or track["title"] != prev["title"] or track["artist"] != prev["artist"]:
                    lyrics = fetch_lyrics(track["artist"], track["title"])
                    _state["track"] = track
                    _state["lyrics"] = lyrics
                    _broadcast("track_change", {
                        "title": track["title"],
                        "artist": track["artist"],
                        "album": track["album"],
                        "lyrics": lyrics,
                    })
                else:
                    _broadcast("position", {"position_ms": track["position_ms"]})
            except SonosUnavailableError:
                _state["track"] = None
                _broadcast("waiting", {})
            except Exception:
                logging.exception("Unexpected error in poll loop")
            time.sleep(poll_interval)

    t = threading.Thread(target=_poll, daemon=True)
    t.start()

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/stream")
    def stream():
        q: queue.SimpleQueue = queue.SimpleQueue()
        with _lock:
            _clients.append(q)
        _has_client.set()

        def generate():
            try:
                while True:
                    try:
                        yield q.get(timeout=30)
                    except queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                with _lock:
                    _clients.remove(q)
                    if not _clients:
                        _has_client.clear()

        return Response(
            stream_with_context(generate()),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    ip = os.environ["SONOS_IP"]
    port = int(os.environ.get("PORT", 5001))
    create_app(ip).run(host="0.0.0.0", port=port, debug=False)

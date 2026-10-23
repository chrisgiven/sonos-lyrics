import json
import logging
import queue
import threading
import time

from flask import Flask, Response, jsonify, request, stream_with_context

from lyrics import fetch_album_art, fetch_artist_info, fetch_lyrics, get_cached_lyrics
from sonos import (
    SonosUnavailableError,
    browse_favorites,
    get_current_track,
    get_speakers,
    get_volume,
    join_group,
    leave_group,
    play_uri,
    set_group_volume,
    set_volume,
    transport_command,
)


def create_app(sonos_ip: str, poll_interval: float = 1.0, initial_delay: float = 0.0) -> Flask:
    app = Flask(__name__, static_folder="static")

    ips = [ip.strip() for ip in sonos_ip.split(",") if ip.strip()]

    # Per-speaker poll threads and client queues: {ip: {clients, lock, has_client, state}}
    _speakers: dict[str, dict] = {}
    _speakers_lock = threading.Lock()

    def _make_speaker_state():
        return {
            "clients": [],
            "lock": threading.Lock(),
            "has_client": threading.Event(),
            # track: last polled track; payload: last track_change sent, replayed to new clients
            "state": {"track": None, "payload": None},
        }

    def _broadcast_to(sp: dict, event: str, data: dict):
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        with sp["lock"]:
            for q in list(sp["clients"]):
                q.put(payload)

    def _lyrics_fields(result: dict) -> dict:
        return {
            "lyrics": result["synced"],
            "plain_lyrics": result["plain"],
            "instrumental": result["instrumental"],
        }

    def _fetch_lyrics_async(sp: dict, track: dict):
        def run():
            fields = _lyrics_fields(fetch_lyrics(track["artist"], track["title"], track.get("duration_ms", 0)))
            payload = sp["state"]["payload"]
            # Drop the result if the song changed while LRCLIB was answering
            if payload is None or (payload["title"], payload["artist"]) != (track["title"], track["artist"]):
                return
            payload.update(fields, lyrics_pending=False)
            _broadcast_to(sp, "lyrics", {"title": track["title"], "artist": track["artist"], **fields})
        threading.Thread(target=run, daemon=True).start()

    def _poll_speaker(ip: str):
        sp = _speakers[ip]
        if initial_delay:
            time.sleep(initial_delay)
        while True:
            sp["has_client"].wait()
            try:
                track = get_current_track(ip)
                prev = sp["state"]["track"]
                if prev is None or track["title"] != prev["title"] or track["artist"] != prev["artist"]:
                    cached = get_cached_lyrics(track["artist"], track["title"]) if track["title"] else None
                    art_url = track.get("art_url", "")
                    if not art_url and (track["artist"] or track["album"]):
                        art_url = fetch_album_art(track["artist"], track["album"])
                    try:
                        volume = get_volume(ip)
                    except SonosUnavailableError:
                        volume = None
                    pending = bool(track["title"]) and cached is None
                    payload = {
                        "title": track["title"],
                        "artist": track["artist"],
                        "album": track["album"],
                        "art_url": art_url,
                        **_lyrics_fields(cached or {"synced": [], "plain": "", "instrumental": False}),
                        "lyrics_pending": pending,
                        "duration_ms": track.get("duration_ms", 0),
                        "volume": volume,
                    }
                    sp["state"]["track"] = track
                    sp["state"]["payload"] = payload
                    _broadcast_to(sp, "track_change", payload)
                    if pending:
                        _fetch_lyrics_async(sp, track)
                else:
                    _broadcast_to(sp, "position", {"position_ms": track["position_ms"]})
            except SonosUnavailableError:
                sp["state"]["track"] = None
                sp["state"]["payload"] = None
                _broadcast_to(sp, "waiting", {})
            except Exception:
                logging.exception("Unexpected error polling %s", ip)
            time.sleep(poll_interval)

    # Start a poll thread for each speaker
    for ip in ips:
        _speakers[ip] = _make_speaker_state()
        t = threading.Thread(target=_poll_speaker, args=(ip,), daemon=True)
        t.start()

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/speakers")
    def speakers_list():
        return jsonify(get_speakers(ips))

    @app.get("/stream")
    def stream():
        ip = request.args.get("ip")
        if ip not in _speakers:
            ip = ips[0]

        sp = _speakers[ip]
        q: queue.SimpleQueue = queue.SimpleQueue()
        with sp["lock"]:
            sp["clients"].append(q)
            # Joining mid-song: send the current track now rather than waiting for the next one
            if sp["state"]["payload"] is not None:
                q.put(f"event: track_change\ndata: {json.dumps(sp['state']['payload'])}\n\n")
        sp["has_client"].set()

        def generate():
            try:
                while True:
                    try:
                        yield q.get(timeout=30)
                    except queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                with sp["lock"]:
                    sp["clients"].remove(q)
                    if not sp["clients"]:
                        sp["has_client"].clear()

        return Response(
            stream_with_context(generate()),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/control")
    def control():
        ip = request.args.get("ip")
        if ip not in _speakers:
            return jsonify({"error": "unknown speaker"}), 400
        data = request.get_json(silent=True) or {}
        action = data.get("action", "")
        if action not in ("play", "pause", "previous", "next"):
            return jsonify({"error": "invalid action"}), 400
        try:
            transport_command(ip, action.capitalize())
            return "", 204
        except SonosUnavailableError as e:
            return jsonify({"error": str(e)}), 503

    @app.get("/favorites")
    def favorites():
        ip = request.args.get("ip")
        if ip not in _speakers:
            return jsonify({"error": "unknown speaker"}), 400
        try:
            return jsonify(browse_favorites(ip))
        except SonosUnavailableError as e:
            return jsonify({"error": str(e)}), 503

    @app.post("/play")
    def play():
        ip = request.args.get("ip")
        if ip not in _speakers:
            return jsonify({"error": "unknown speaker"}), 400
        data = request.get_json(silent=True) or {}
        uri = (data.get("uri") or "").strip()
        if not uri:
            return jsonify({"error": "uri required"}), 400
        metadata = data.get("metadata") or ""
        try:
            play_uri(ip, uri, metadata)
            return "", 204
        except SonosUnavailableError as e:
            return jsonify({"error": str(e)}), 503

    @app.get("/artist")
    def artist():
        name = request.args.get("name", "").strip()
        art_url = request.args.get("art_url", "").strip()
        return jsonify(fetch_artist_info(name, art_url))

    @app.post("/volume")
    def volume():
        ip = request.args.get("ip")
        if ip not in _speakers:
            return jsonify({"error": "unknown speaker"}), 400
        data = request.get_json(silent=True) or {}
        level = data.get("level")
        if not isinstance(level, int) or not 0 <= level <= 100:
            return jsonify({"error": "level must be 0–100"}), 400
        try:
            # {"group": true} sets the whole group's volume via the coordinator.
            if data.get("group"):
                set_group_volume(ip, level)
            else:
                set_volume(ip, level)
            return "", 204
        except SonosUnavailableError as e:
            return jsonify({"error": str(e)}), 503

    @app.post("/group")
    def group():
        # ip = coordinator (the room being followed). body: {action, member}
        ip = request.args.get("ip")
        if ip not in _speakers:
            return jsonify({"error": "unknown speaker"}), 400
        data = request.get_json(silent=True) or {}
        action = data.get("action", "")
        member = data.get("member", "")
        if action not in ("join", "leave") or not isinstance(member, str) or not member:
            return jsonify({"error": "invalid group request"}), 400
        try:
            if action == "join":
                join_group(member, ip)
            else:
                leave_group(member)
            return "", 204
        except SonosUnavailableError as e:
            return jsonify({"error": str(e)}), 503

    return app


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    ip = os.environ["SONOS_IP"]
    port = int(os.environ.get("PORT", 5001))
    create_app(ip).run(host="0.0.0.0", port=port, debug=False)

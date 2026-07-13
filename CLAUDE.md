# Sonos Lyrics — Claude notes

Flask local server streaming synced lyrics for Sonos playback. Port 5001.

## Architecture (5 lines)
- `sonos.py` — UPnP SOAP client: track info, transport commands, volume (Sonos S2 needs SOAP, not the old status URL)
- `lyrics.py` — LRCLIB fetch + LRC parse; MusicBrainz/CAA album-art fallback
- `server.py` — Flask app, per-speaker SSE streams (`/events`), control/volume routes
- `static/` — lyric view with RAF-driven sync scrolling, speaker picker, player bar
- `tests/` — pytest suite (28 tests)

## Run / Verify
```bash
python3 server.py            # → http://localhost:5001
python3 -m pytest -q         # verify: expect 28 passed
```

## Deploy decision
NAS docker at 192.168.1.94 via `docker-compose.yml` (speaker IPs hardcoded in compose env). See `/deploy-nas`.

## Gotchas
- **LRCLIB times out from this network** (~15s timeout already raised) — known blocker; don't burn time "fixing" fetch code before checking connectivity.
- Speaker discovery is via the `SONOS_IP` comma-separated list, not SSDP.
- Polling stops when no SSE clients are connected — don't "fix" the idle server.
- `docs/superpowers/` and `.superpowers/` are planning scratch, gitignored.

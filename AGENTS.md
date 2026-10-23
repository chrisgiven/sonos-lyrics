# Sonos Lyrics — Claude notes

Flask local server streaming synced lyrics for Sonos playback. Port 5001.

## Architecture (5 lines)
- `sonos.py` — UPnP SOAP client: track info, transport commands, volume (Sonos S2 needs SOAP, not the old status URL)
- `lyrics.py` — LRCLIB lookup (exact → cleaned title → `q=` search, matched on duration) + SQLite cache at `cache/lyrics.db` (`LYRICS_CACHE_PATH`); MusicBrainz/CAA album art; Wikipedia bio
- `server.py` — Flask app, per-speaker SSE streams (`/stream`): `track_change`, then a `lyrics` event when the lookup wasn't cached; control/volume routes
- `static/` — lyric view with RAF-driven sync scrolling, speaker picker, player bar
- `tests/` — pytest suite (52 tests)

## Run / Verify
```bash
python3 server.py            # → http://localhost:5001
python3 -m pytest -q         # verify: expect 52 passed
```

## Deploy decision
NAS docker at 192.168.1.94 via `docker-compose.yml` (speaker IPs hardcoded in compose env). See `/deploy-nas`.

## Gotchas
- LRCLIB answers a miss with **503** as often as 404 — that's normal, not an outage. `/api/search` is different: its structured form (`track_name`+`artist_name`) always 503s (use `q=`), and `q=` itself 503s intermittently, so a search 503 is retried once and never cached as a miss.
- Lyric misses are cached for an hour, hits forever; network errors aren't cached. Delete `cache/lyrics.db` to force refetches.
- Speaker discovery is via the `SONOS_IP` comma-separated list, not SSDP.
- Polling stops when no SSE clients are connected — don't "fix" the idle server.
- `docs/superpowers/` and `.superpowers/` are planning scratch, gitignored.

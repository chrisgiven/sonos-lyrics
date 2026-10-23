# Sonos Lyrics

Real-time synced lyrics for whatever your Sonos speakers are playing. A local Flask server polls the speakers over UPnP/SOAP, fetches timed lyrics from LRCLIB, and streams updates to the browser over SSE with karaoke-style scrolling.

## Features

- Rooms sheet with per-speaker now-playing info, plus Sonos grouping (add/remove rooms, group and per-room volume)
- Synced lyric scrolling (LRC timing); falls back to plain lyrics or "Instrumental"
- Smart LRCLIB matching (duration, remaster/live/feat. tag cleanup, search fallback) with an on-disk cache
- Playback controls: play/pause/skip, progress bar, volume slider
- Album art with MusicBrainz/Cover Art Archive fallback
- Artist bio (Wikipedia) on the no-lyrics screen
- Browse and play Sonos Favorites

## Run

```bash
pip install -r requirements.txt
cp .env.example .env   # set SONOS_IP to comma-separated speaker IPs
python3 server.py       # → http://localhost:5001 (PORT env to change)
```

## Test

```bash
python3 -m pytest -q
```

## Deploy

NAS docker (Asustor, 192.168.1.94) via `docker-compose.yml`; speaker IPs are set in the compose environment.

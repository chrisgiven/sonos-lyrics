# Sonos Lyrics Display — Design Spec
**Date:** 2026-05-30

## Overview

A local Python Flask app that detects the currently playing track on a Sonos speaker, fetches synced (timestamped) lyrics from LRCLIB, and displays them in a phone-friendly web page that scrolls and highlights lines in real time as the song plays.

No accounts, no API keys, no cloud infrastructure required. Runs on the user's Mac; accessed from any device on the same WiFi.

---

## Architecture

```
[ Sonos speaker (local network) ]
        ↓  HTTP GET :1400/status/trackinfo  (every 1s)
[ Flask server on Mac ]
        ↓  on track change → GET lrclib.net/api/get
[ LRCLIB lyrics API ]
        ↓  SSE stream (/stream) + static page (/)
[ Phone/tablet browser ]
```

---

## Components

### `sonos.py`
- Polls `http://<SONOS_IP>:1400/status/trackinfo` every second
- Parses XML response for: `title`, `artist`, `album`, `reltime` (current position as `HH:MM:SS`)
- Exposes `get_current_track() -> dict` returning `{title, artist, album, position_ms}`
- Raises `SonosUnavailableError` if the speaker is unreachable

### `lyrics.py`
- `fetch_lyrics(artist, title) -> list[{time_ms: int, text: str}]`
- Calls `https://lrclib.net/api/get?artist_name=<artist>&track_name=<title>`
- Parses the `syncedLyrics` field (LRC format: `[mm:ss.xx] line text`)
- Returns list of `{time_ms, text}` dicts sorted by time
- Returns empty list if no synced lyrics found (non-fatal)
- In-memory cache keyed by `(artist, title)` — cleared on process restart

### `server.py`
- Flask app with two routes:
  - `GET /` — serves `static/index.html`
  - `GET /stream` — SSE endpoint, keeps connection open
- Background thread polls Sonos every second:
  - On track change: fetches lyrics, broadcasts `track_change` event
  - Every tick: broadcasts `position` event
- SSE event types:
  - `track_change`: `{title, artist, album, lyrics: [{time_ms, text}]}`
  - `position`: `{position_ms}`
  - `waiting`: emitted when Sonos is unreachable (no track data)

### `static/index.html`
- Single HTML file with embedded CSS and JS (no build step)
- Connects to `/stream` via `EventSource`
- On `track_change`: renders track metadata + lyric lines as a scrollable list
- On `position`: binary-searches lyric array for active line (`last line where time_ms ≤ position_ms`), adds `.active` class, smoothly scrolls active line to vertical center
- States:
  - **Waiting** — "Waiting for Sonos…" spinner (Sonos unreachable or nothing playing)
  - **No lyrics** — "No lyrics available for this track"
  - **Playing** — full lyrics display with active line highlighted
- Design: dark background, large readable text, high contrast — optimized for phone use

---

## Data Flow

1. App starts; reads `SONOS_IP` from `.env` (via `python-dotenv`)
2. Background thread begins polling `sonos.py` every second
3. **Track change detected:**
   - Call `lyrics.py → fetch_lyrics(artist, title)`
   - Push `track_change` SSE event to all connected clients with full lyric array
4. **Every second:**
   - Push `position` SSE event with current `position_ms`
5. **Browser on `track_change`:**
   - Re-render lyric lines
6. **Browser on `position`:**
   - Binary search for active lyric line
   - Highlight + scroll to center

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Sonos unreachable | Push `waiting` SSE event; page shows spinner; retry every second |
| LRCLIB returns no synced lyrics | `lyrics` array is empty; page shows "No lyrics available" |
| LRCLIB request fails (network/timeout) | Log warning; treat as no lyrics |
| Browser disconnects | SSE connection closes; no server-side impact |
| Multiple browsers connected | All receive the same SSE broadcast |

---

## Setup

```bash
# 1. Install dependencies
pip install flask python-dotenv requests

# 2. Configure
echo "SONOS_IP=192.168.x.x" > .env   # your speaker's local IP

# 3. Run
flask --app server run --host=0.0.0.0 --port=5000

# 4. Open on phone
# Navigate to http://<your-mac-ip>:5000
```

To find your Sonos speaker's IP: open the Sonos app → Settings → System → (select room) → About My System.

---

## File Structure

```
sonos-lyrics/
├── sonos.py
├── lyrics.py
├── server.py
├── static/
│   └── index.html
├── .env              # SONOS_IP (gitignored)
├── .gitignore
└── requirements.txt
```

---

## Out of Scope

- Authentication / multi-user access
- Support for Spotify, Amazon Music, or Plex lyrics (can be added later)
- Hosting / cloud deployment (local-only by design)
- Mobile native app (browser is sufficient)
- Offline lyrics caching across restarts

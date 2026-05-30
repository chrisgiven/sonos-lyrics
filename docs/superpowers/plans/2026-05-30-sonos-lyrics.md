# Sonos Lyrics Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Flask web app that polls Sonos for the currently playing track, fetches synced lyrics from LRCLIB, and displays them in a phone-friendly page that highlights and scrolls lyrics in real time.

**Architecture:** A Flask server runs on the user's Mac with a background thread polling the Sonos local HTTP API every second. Track changes trigger a LRCLIB lyrics fetch; playback position is broadcast every second to all connected browsers via Server-Sent Events. The browser uses these events to highlight and scroll the active lyric line.

**Tech Stack:** Python 3.10+, Flask 3.x, python-dotenv, requests, pytest — no frontend build tooling (single static HTML file).

---

## File Structure

```
sonos-lyrics/
├── sonos.py              # Sonos polling: get_current_track()
├── lyrics.py             # LRCLIB fetch + LRC parse: fetch_lyrics()
├── server.py             # Flask app + SSE + background thread
├── static/
│   └── index.html        # Single-page lyrics UI
├── tests/
│   ├── test_sonos.py
│   ├── test_lyrics.py
│   └── test_server.py
├── .env.example
├── .gitignore
└── requirements.txt
```

---

### Task 1: Project scaffold

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`

- [ ] **Step 1: Create requirements.txt**

```
flask>=3.0
python-dotenv>=1.0
requests>=2.31
pytest>=8.0
pytest-flask>=1.3
responses>=0.25
```

- [ ] **Step 2: Create .env.example**

```
SONOS_IP=192.168.1.x
```

- [ ] **Step 3: Create .gitignore**

```
.env
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -r requirements.txt
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example .gitignore
git commit -m "chore: project scaffold"
```

---

### Task 2: Sonos polling module

**Files:**
- Create: `sonos.py`
- Create: `tests/test_sonos.py`

The Sonos local HTTP API returns XML from `http://<ip>:1400/status/trackinfo`. Example response:

```xml
<TrackInfo>
  <title>Bohemian Rhapsody</title>
  <artist>Queen</artist>
  <album>A Night at the Opera</album>
  <reltime>0:01:23</reltime>
  <duration>0:05:55</duration>
</TrackInfo>
```

`reltime` is the current playback position as `H:MM:SS` or `M:SS`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_sonos.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sonos.py -v
```
Expected: `ModuleNotFoundError: No module named 'sonos'`

- [ ] **Step 3: Implement sonos.py**

```python
import requests
import xml.etree.ElementTree as ET


class SonosUnavailableError(Exception):
    pass


def _parse_reltime(reltime: str) -> int:
    """Convert H:MM:SS or M:SS to milliseconds."""
    parts = reltime.strip().split(":")
    parts = [int(p) for p in parts]
    if len(parts) == 3:
        h, m, s = parts
    else:
        h, m, s = 0, parts[0], parts[1]
    return (h * 3600 + m * 60 + s) * 1000


def get_current_track(ip: str) -> dict:
    """Poll Sonos trackinfo endpoint. Raises SonosUnavailableError on failure."""
    url = f"http://{ip}:1400/status/trackinfo"
    try:
        resp = requests.get(url, timeout=2)
        resp.raise_for_status()
    except Exception as e:
        raise SonosUnavailableError(str(e)) from e

    root = ET.fromstring(resp.text)
    return {
        "title": root.findtext("title", "").strip(),
        "artist": root.findtext("artist", "").strip(),
        "album": root.findtext("album", "").strip(),
        "position_ms": _parse_reltime(root.findtext("reltime", "0:00")),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sonos.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sonos.py tests/test_sonos.py
git commit -m "feat: sonos polling module"
```

---

### Task 3: Lyrics fetch and parse module

**Files:**
- Create: `lyrics.py`
- Create: `tests/test_lyrics.py`

LRCLIB API: `GET https://lrclib.net/api/get?artist_name=Queen&track_name=Bohemian+Rhapsody`

Returns JSON with a `syncedLyrics` field containing LRC-format text:
```
[00:00.00] 
[00:49.37] Is this the real life?
[00:52.48] Is this just fantasy?
```

Lines starting with `[00:00.00] ` (empty text) are instrumental gaps — include them as empty strings so the display can show silence.

- [ ] **Step 1: Write failing tests**

Create `tests/test_lyrics.py`:

```python
import pytest
import responses as resp_mock
from lyrics import fetch_lyrics, _parse_lrc

SAMPLE_LRC = """\
[00:00.00] 
[00:49.37] Is this the real life?
[00:52.48] Is this just fantasy?
[01:30.00] Mama, just killed a man
"""

def test_parse_lrc_returns_sorted_list():
    result = _parse_lrc(SAMPLE_LRC)
    assert result[0] == {"time_ms": 0, "text": ""}
    assert result[1] == {"time_ms": 49370, "text": "Is this the real life?"}
    assert result[2] == {"time_ms": 52480, "text": "Is this just fantasy?"}
    assert result[3] == {"time_ms": 90000, "text": "Mama, just killed a man"}

@resp_mock.activate
def test_fetch_lyrics_returns_parsed_lines():
    resp_mock.add(
        resp_mock.GET,
        "https://lrclib.net/api/get",
        json={"syncedLyrics": SAMPLE_LRC},
        status=200,
    )
    result = fetch_lyrics("Queen", "Bohemian Rhapsody")
    assert len(result) == 4
    assert result[1]["text"] == "Is this the real life?"

@resp_mock.activate
def test_fetch_lyrics_returns_empty_on_no_synced_lyrics():
    resp_mock.add(
        resp_mock.GET,
        "https://lrclib.net/api/get",
        json={"syncedLyrics": None, "plainLyrics": "some text"},
        status=200,
    )
    result = fetch_lyrics("Unknown", "Track")
    assert result == []

@resp_mock.activate
def test_fetch_lyrics_returns_empty_on_404():
    resp_mock.add(
        resp_mock.GET,
        "https://lrclib.net/api/get",
        status=404,
    )
    result = fetch_lyrics("Nobody", "Nowhere")
    assert result == []

def test_fetch_lyrics_caches_result():
    # Call twice with same args — should only hit network once
    import lyrics as lyr
    lyr._cache.clear()
    call_count = 0

    import responses as resp_m
    with resp_m.RequestsMock() as rsps:
        rsps.add(
            rsps.GET,
            "https://lrclib.net/api/get",
            json={"syncedLyrics": SAMPLE_LRC},
        )
        lyr.fetch_lyrics("Queen", "Bohemian Rhapsody")
        lyr.fetch_lyrics("Queen", "Bohemian Rhapsody")
        assert len(rsps.calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_lyrics.py -v
```
Expected: `ModuleNotFoundError: No module named 'lyrics'`

- [ ] **Step 3: Implement lyrics.py**

```python
import re
import requests

_cache: dict = {}
_LRCLIB_URL = "https://lrclib.net/api/get"
_LINE_RE = re.compile(r"\[(\d{2}):(\d{2})\.(\d{2,3})\]\s*(.*)")


def _parse_lrc(lrc_text: str) -> list[dict]:
    """Parse LRC format into [{time_ms, text}] sorted by time."""
    lines = []
    for line in lrc_text.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        minutes, seconds, centis, text = m.groups()
        # centis may be 2 or 3 digits; normalise to ms
        centis_int = int(centis)
        if len(centis) == 2:
            centis_int *= 10
        time_ms = (int(minutes) * 60 + int(seconds)) * 1000 + centis_int
        lines.append({"time_ms": time_ms, "text": text.strip()})
    return sorted(lines, key=lambda x: x["time_ms"])


def fetch_lyrics(artist: str, title: str) -> list[dict]:
    """Fetch synced lyrics from LRCLIB. Returns [] if unavailable."""
    key = (artist.lower(), title.lower())
    if key in _cache:
        return _cache[key]

    try:
        resp = requests.get(
            _LRCLIB_URL,
            params={"artist_name": artist, "track_name": title},
            timeout=5,
        )
        if resp.status_code == 404:
            _cache[key] = []
            return []
        resp.raise_for_status()
        data = resp.json()
        synced = data.get("syncedLyrics")
        result = _parse_lrc(synced) if synced else []
    except Exception:
        result = []

    _cache[key] = result
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_lyrics.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add lyrics.py tests/test_lyrics.py
git commit -m "feat: lyrics fetch and LRC parse module"
```

---

### Task 4: Flask server with SSE

**Files:**
- Create: `server.py`
- Create: `tests/test_server.py`

The server has two routes: `GET /` serves `static/index.html`, and `GET /stream` is a Server-Sent Events endpoint. A background daemon thread polls Sonos every second and pushes events to all connected clients via a thread-safe queue.

- [ ] **Step 1: Write failing tests**

Create `tests/test_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_server.py -v
```
Expected: `ModuleNotFoundError: No module named 'server'`

- [ ] **Step 3: Implement server.py**

```python
import json
import queue
import threading
import time

from flask import Flask, Response, stream_with_context

from lyrics import fetch_lyrics
from sonos import SonosUnavailableError, get_current_track


def create_app(sonos_ip: str) -> Flask:
    app = Flask(__name__, static_folder="static")

    # Shared state
    _state = {"track": None, "lyrics": []}
    _clients: list[queue.SimpleQueue] = []
    _lock = threading.Lock()

    def _broadcast(event: str, data: dict):
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        with _lock:
            for q in list(_clients):
                q.put(payload)

    def _poll():
        while True:
            try:
                track = get_current_track(sonos_ip)
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
            time.sleep(1)

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
    create_app(ip).run(host="0.0.0.0", port=5000, debug=False)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_server.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: flask server with SSE broadcast"
```

---

### Task 5: Phone-friendly lyrics UI

**Files:**
- Create: `static/index.html`

No build step — single HTML file with embedded CSS and JS.

UI states:
1. **Connecting** — shown on load before first SSE event
2. **Waiting** — "Waiting for Sonos…" with a pulsing dot
3. **No lyrics** — track name shown, "No lyrics available"
4. **Playing** — full lyric list; active line highlighted and scrolled to centre

- [ ] **Step 1: Create static/index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Sonos Lyrics</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: #0d0d0d;
    color: #888;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    min-height: 100dvh;
    overflow-x: hidden;
  }

  #meta {
    position: sticky;
    top: 0;
    background: #0d0d0ddd;
    backdrop-filter: blur(12px);
    padding: 16px 20px 12px;
    border-bottom: 1px solid #1a1a1a;
    z-index: 10;
  }

  #title { font-size: 1.05rem; font-weight: 600; color: #eee; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #artist { font-size: 0.85rem; color: #666; margin-top: 2px; }

  #lyrics {
    padding: 40vh 20px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }

  .line {
    font-size: 1.4rem;
    line-height: 1.45;
    color: #3a3a3a;
    transition: color 0.25s ease, transform 0.25s ease;
    cursor: default;
  }

  .line.active {
    color: #ffffff;
    transform: scale(1.03);
    transform-origin: left center;
  }

  #status {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 80dvh;
    font-size: 1rem;
    color: #555;
    gap: 10px;
  }

  .dot {
    width: 8px; height: 8px;
    background: #555;
    border-radius: 50%;
    animation: pulse 1.4s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.3; transform: scale(0.8); }
    50% { opacity: 1; transform: scale(1.2); }
  }
</style>
</head>
<body>

<div id="meta" style="display:none">
  <div id="title"></div>
  <div id="artist"></div>
</div>

<div id="status">
  <div class="dot"></div>
  <span id="status-text">Connecting…</span>
</div>

<div id="lyrics" style="display:none"></div>

<script>
  const metaEl = document.getElementById("meta");
  const titleEl = document.getElementById("title");
  const artistEl = document.getElementById("artist");
  const statusEl = document.getElementById("status");
  const statusTextEl = document.getElementById("status-text");
  const lyricsEl = document.getElementById("lyrics");

  let lines = [];        // [{time_ms, text}]
  let activeIdx = -1;
  let positionMs = 0;
  let rafId = null;

  function showStatus(msg) {
    metaEl.style.display = "none";
    lyricsEl.style.display = "none";
    statusEl.style.display = "flex";
    statusTextEl.textContent = msg;
  }

  function renderTrack(data) {
    titleEl.textContent = data.title || "Unknown";
    artistEl.textContent = data.artist || "";
    lines = data.lyrics || [];
    activeIdx = -1;

    metaEl.style.display = "block";
    statusEl.style.display = "none";

    if (lines.length === 0) {
      lyricsEl.style.display = "none";
      showStatus("No lyrics available");
      metaEl.style.display = "block";
      statusEl.style.display = "flex";
      return;
    }

    lyricsEl.innerHTML = lines
      .map((l, i) => `<div class="line" id="line-${i}">${l.text || "&nbsp;"}</div>`)
      .join("");
    lyricsEl.style.display = "flex";
  }

  function updateActive(pMs) {
    if (lines.length === 0) return;

    // Binary search for last line with time_ms <= pMs
    let lo = 0, hi = lines.length - 1, idx = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (lines[mid].time_ms <= pMs) { idx = mid; lo = mid + 1; }
      else hi = mid - 1;
    }

    if (idx === activeIdx) return;
    if (activeIdx >= 0) {
      document.getElementById(`line-${activeIdx}`)?.classList.remove("active");
    }
    activeIdx = idx;
    if (activeIdx >= 0) {
      const el = document.getElementById(`line-${activeIdx}`);
      if (el) {
        el.classList.add("active");
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }
  }

  // Smooth position interpolation between server ticks
  let lastServerMs = 0;
  let lastServerTimestamp = 0;

  function tick() {
    const elapsed = Date.now() - lastServerTimestamp;
    const interpolated = lastServerMs + elapsed;
    updateActive(interpolated);
    rafId = requestAnimationFrame(tick);
  }

  const es = new EventSource("/stream");

  es.addEventListener("track_change", e => {
    const data = JSON.parse(e.data);
    renderTrack(data);
    lastServerMs = 0;
    lastServerTimestamp = Date.now();
    if (!rafId) rafId = requestAnimationFrame(tick);
  });

  es.addEventListener("position", e => {
    const data = JSON.parse(e.data);
    lastServerMs = data.position_ms;
    lastServerTimestamp = Date.now();
  });

  es.addEventListener("waiting", () => {
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    showStatus("Waiting for Sonos…");
  });

  es.onerror = () => showStatus("Reconnecting…");
</script>
</body>
</html>
```

- [ ] **Step 2: Start the server and open in browser to verify**

```bash
# Copy .env.example to .env and set your Sonos speaker IP
cp .env.example .env
# Edit .env: SONOS_IP=192.168.x.x

python server.py
```

Open `http://localhost:5000` — should show "Waiting for Sonos…" if IP isn't set, or lyrics if Sonos is playing.

On your phone (same WiFi): open `http://<your-mac-ip>:5000`.

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat: lyrics UI with real-time sync scrolling"
```

---

### Task 6: Run full test suite and final commit

- [ ] **Step 1: Run all tests**

```bash
pytest -v
```
Expected: all tests pass (12 total across test_sonos, test_lyrics, test_server)

- [ ] **Step 2: Verify no import errors**

```bash
python -c "from server import create_app; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: verify full test suite passes"
```

---

## Running the App

```bash
# One-time setup
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set SONOS_IP to your speaker's local IP
# (Sonos app → Settings → System → [room] → About My System)

# Start
python server.py

# Access from phone on same WiFi
# http://<your-mac-ip>:5000
```

To find your Mac's local IP: `ipconfig getifaddr en0` (WiFi) or `ipconfig getifaddr en1`.

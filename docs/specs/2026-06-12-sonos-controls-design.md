# Sonos Playback Controls Design

**Date:** 2026-06-12  
**Status:** Approved  
**Approach:** B — Controls + Visual Polish

## Overview

Add full playback controls to the Sonos lyrics app: play/pause, previous/next track, volume slider, display-only progress bar, and visual polish (animated equalizer, time labels, volume percentage).

## Backend

### New functions in `sonos.py`

**`transport_command(ip: str, cmd: str) -> None`**  
Sends a SOAP `AVTransport` action to the speaker. `cmd` is one of `Play`, `Pause`, `Previous`, `Next`. Raises `SonosUnavailableError` on failure.

**`set_volume(ip: str, level: int) -> None`**  
Sends `RenderingControl:SetVolume` with `DesiredVolume` = `level` (0–100). Raises `SonosUnavailableError` on failure.

**`get_volume(ip: str) -> int`**  
Sends `RenderingControl:GetVolume`. Returns current volume 0–100. Raises `SonosUnavailableError` on failure.

### New routes in `server.py`

**`POST /control?ip=<ip>`**  
Body: `{"action": "play" | "pause" | "previous" | "next"}`  
Calls `transport_command(ip, action.capitalize())`. Returns `204` on success, `400` on bad action, `503` on `SonosUnavailableError`.

**`POST /volume?ip=<ip>`**  
Body: `{"level": 0–100}`  
Validates range, calls `set_volume(ip, level)`. Returns `204` on success, `400` on bad input, `503` on `SonosUnavailableError`.

### SSE payload changes

`track_change` event gains two new fields:
- `volume` (int 0–100) — fetched via `get_volume` at track-change time
- `duration_ms` (int) — parsed from `TrackDuration` in the existing `GetPositionInfo` SOAP response (currently unused)

No new polling. Volume is fetched once per track change; duration is already in the SOAP response.

## Frontend

### Progress bar

- Thin (3px) bar sitting flush above the player bar, full viewport width
- Fills left-to-right: `position_ms / duration_ms * 100%`
- Updated every RAF tick (same loop already running for lyric sync)
- Elapsed time label (e.g. `0:47`) on the left, remaining (e.g. `-2:13`) on the right
- Labels in `0.65rem`, `rgba(255,255,255,0.4)`, updated every second (not every RAF tick)
- Not interactive — display only

### Player bar (`#player-bar`)

Fixed to the bottom of the viewport. Same glass treatment as the header: `backdrop-filter: blur(20px)`, dark semi-transparent background, top border at `rgba(255,255,255,0.08)`.

Layout (single row, safe-area-aware bottom padding):
```
[🔈 ──────────── slider ──────────────] [⏮  ⏸/▶  ⏭]
```

**Volume section (left ~55%):**
- Speaker icon on the far left. Tap to mute (sends `set_volume` with 0) / unmute (restores last level)
- `<input type="range">` styled to match the dark theme — no default browser chrome
- Percentage label (`65%`) appears at the slider thumb while dragging, fades out 1.5s after `pointerup` (CSS opacity transition, no layout shift)
- On `input` event: update label immediately. On `change` event: `POST /volume`

**Transport section (right):**
- Prev (24px circle), Play/Pause (36px circle, prominent), Next (24px circle)
- Each tap fires `POST /control` with the relevant action
- Buttons get `opacity: 0.4` for 300ms after tap as tactile feedback, then restore

**Visibility:**
- Hidden during speaker picker and "nothing playing" status screen
- Fades in (0.3s) when a `track_change` event arrives
- `#lyrics` and status screen get `padding-bottom` extended to clear the bar height

### Play/pause state sync

The play-pause button icon tracks actual Sonos state, not just optimistic UI:
- Switches to ▶ if `position_ms` stops advancing for 3 consecutive 1-second ticks
- Switches to ⏸ when a `position` event arrives with a new `position_ms`
- Handles pause from any source (Sonos app, Alexa, physical button)

### Animated equalizer

Three vertical bars next to the album art thumbnail in the header. Visible only when music is playing (hidden when paused or idle). Pure CSS keyframe animation — no JS, no audio analysis.

Each bar bounces at a different speed (0.6s, 0.9s, 0.75s) and height range (4–14px). Color: `rgba(255,255,255,0.7)`. Width: 3px, gap: 3px. Animates in/out with a 0.2s opacity transition.

On the speaker picker, the active (playing) speaker's animated dot is replaced by the same three-bar equalizer.

## Error Handling

- Control and volume `POST` requests show no UI error on failure — the next SSE poll will correct any stale state within 1 second
- If `get_volume` fails during `track_change`, volume defaults to `null` and the slider renders at 50% as a fallback
- If `duration_ms` is 0 or missing (radio streams), the progress bar is hidden and time labels are not shown

## Out of Scope

- Seek / scrub (progress bar is display-only)
- Shuffle / repeat toggles
- Group / multi-room volume
- Queue display

# Changelog

## 2026-10-23 (merge)
- merge: speaker grouping (join/leave, group volume) and the redesigned UI (album-art accent, blur-focus lyrics, Rooms sheet), recovered from uncommitted edits on the NAS clone
- feat: Favorites and the new lyric states (looking up / plain / instrumental) ported into the redesigned UI; the empty-room "Browse music" button opens Favorites
- fix: album art for streaming tracks (relative `/getaa` paths now point at the speaker); art retries once while the speaker caches it
- chore: remove a design-tool preview script that had been left in index.html
- change: the redesign drops the artist bio + photo panel under the lyrics; the bio now shows only on the no-lyrics screen
- test: grouping (topology parsing, join/leave, group volume, /group route)

## 2026-10-23
- feat: lyric lookup sends track duration, retries with version tags stripped ("- Remastered 2011", "(Live)", "feat. X"), then falls back to LRCLIB search picking the closest-length match
- feat: show plain (unsynced) lyrics and "Instrumental" instead of "No lyrics available"
- feat: SQLite lyrics cache (`cache/lyrics.db`, mounted as a volume on the NAS) — hits kept forever, misses retried after an hour; transient LRCLIB errors no longer hide a song until restart
- feat: uncached lyrics load in the background so the track header and progress update immediately
- fix: a second device joining mid-song now gets the current track instead of a blank screen
- docs: drop the stale "LRCLIB times out" blocker

## 2026-07-13
- chore: bring project up to house standard (README, CLAUDE.md, ROADMAP, CHANGELOG; ignore .superpowers/)

## 2026-06-20
- feat: browse and play Sonos Favorites from the UI

## 2026-06-17
- feat: artist bio + photo panel below lyrics, with Wikipedia link

## 2026-06-12
- feat: playback controls — transport commands, progress bar, volume slider, player bar UI

## 2026-06-06
- feat: room navigation and now-playing info in speaker picker

## 2026-06-04
- feat: MusicBrainz/CAA fallback album art

## 2026-05-30
- Initial build: Sonos UPnP/SOAP polling, LRCLIB lyrics with LRC sync scrolling, Flask + SSE, speaker picker, multi-IP auto-detect, Dockerfile/compose for Asustor NAS

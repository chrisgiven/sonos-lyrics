import time

import pytest
import requests
import responses as resp_mock

import lyrics
from lyrics import _parse_lrc, clean_title, fetch_lyrics, get_cached_lyrics, primary_artist

GET_URL = "https://lrclib.net/api/get"
SEARCH_URL = "https://lrclib.net/api/search"

SAMPLE_LRC = """\
[00:00.00]
[00:49.37] Is this the real life?
[00:52.48] Is this just fantasy?
[01:30.00] Mama, just killed a man
"""


def _record(title="Bohemian Rhapsody", artist="Queen", duration=354, synced=SAMPLE_LRC,
            plain="Is this the real life?", instrumental=False):
    return {"trackName": title, "artistName": artist, "duration": duration,
            "syncedLyrics": synced, "plainLyrics": plain, "instrumental": instrumental}


def test_parse_lrc_returns_sorted_list():
    result = _parse_lrc(SAMPLE_LRC)
    assert result[0] == {"time_ms": 0, "text": ""}
    assert result[1] == {"time_ms": 49370, "text": "Is this the real life?"}
    assert result[2] == {"time_ms": 52480, "text": "Is this just fantasy?"}
    assert result[3] == {"time_ms": 90000, "text": "Mama, just killed a man"}


@pytest.mark.parametrize("raw, expected", [
    ("Bohemian Rhapsody - Remastered 2011", "Bohemian Rhapsody"),
    ("Dreams (2004 Remaster)", "Dreams"),
    ("Two Note Swivel (Unfinished Outtake)", "Two Note Swivel"),
    ("Get Lucky (Radio Edit) [feat. Pharrell Williams]", "Get Lucky"),
    ("Get Lucky feat. Pharrell Williams", "Get Lucky"),
    ("Hey Jude - Live At The Hollywood Bowl", "Hey Jude"),
    ("Paranoid Android", "Paranoid Android"),
    ("Mr. Brightside", "Mr. Brightside"),
    ("Love Me Do (with Strings)", "Love Me Do"),
])
def test_clean_title(raw, expected):
    assert clean_title(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Daft Punk, Pharrell Williams", "Daft Punk"),
    ("Daft Punk feat. Pharrell Williams", "Daft Punk"),
    ("Mark Ronson & Bruno Mars", "Mark Ronson"),
    ("Queen", "Queen"),
])
def test_primary_artist(raw, expected):
    assert primary_artist(raw) == expected


@resp_mock.activate
def test_fetch_lyrics_returns_synced_and_plain():
    resp_mock.add(resp_mock.GET, GET_URL, json=_record())
    result = fetch_lyrics("Queen", "Bohemian Rhapsody")
    assert len(result["synced"]) == 4
    assert result["synced"][1]["text"] == "Is this the real life?"
    assert result["plain"] == "Is this the real life?"
    assert result["instrumental"] is False


@resp_mock.activate
def test_fetch_lyrics_sends_duration_in_seconds():
    resp_mock.add(resp_mock.GET, GET_URL, json=_record())
    fetch_lyrics("Queen", "Bohemian Rhapsody", duration_ms=354_400)
    assert "duration=354" in resp_mock.calls[0].request.url


@resp_mock.activate
def test_fetch_lyrics_retries_with_cleaned_title():
    resp_mock.add(resp_mock.GET, GET_URL, status=503,
                  match=[resp_mock.matchers.query_param_matcher(
                      {"artist_name": "Queen", "track_name": "Bohemian Rhapsody - Remastered 2011"})])
    resp_mock.add(resp_mock.GET, GET_URL, json=_record(),
                  match=[resp_mock.matchers.query_param_matcher(
                      {"artist_name": "Queen", "track_name": "Bohemian Rhapsody"})])
    result = fetch_lyrics("Queen", "Bohemian Rhapsody - Remastered 2011")
    assert len(result["synced"]) == 4


@resp_mock.activate
def test_fetch_lyrics_falls_back_to_search_and_picks_closest_duration():
    resp_mock.add(resp_mock.GET, GET_URL, status=404)
    resp_mock.add(resp_mock.GET, GET_URL, status=404)
    wrong_version = _record(duration=263, synced="[00:01.00] wrong version")
    right_version = _record(duration=352)
    other_song = _record(title="Bohemian Rhapsody Tribute", duration=352, synced="[00:01.00] other")
    resp_mock.add(resp_mock.GET, SEARCH_URL, json=[wrong_version, other_song, right_version])
    result = fetch_lyrics("Queen", "Bohemian Rhapsody (Live)", duration_ms=354_000)
    assert result["synced"][1]["text"] == "Is this the real life?"
    assert "q=Bohemian+Rhapsody+Queen" in resp_mock.calls[-1].request.url


@resp_mock.activate
def test_search_demotes_synced_from_wrong_length_to_plain():
    resp_mock.add(resp_mock.GET, GET_URL, status=404)
    resp_mock.add(resp_mock.GET, SEARCH_URL, json=[_record(duration=200, plain="")])
    result = fetch_lyrics("Queen", "Bohemian Rhapsody", duration_ms=354_000)
    assert result["synced"] == []
    assert "Is this the real life?" in result["plain"]


@resp_mock.activate
def test_fetch_lyrics_returns_plain_when_no_synced_anywhere():
    resp_mock.add(resp_mock.GET, GET_URL, json=_record(synced=None, plain="line one\nline two"))
    resp_mock.add(resp_mock.GET, SEARCH_URL, json=[])
    result = fetch_lyrics("Unknown", "Track")
    assert result == {"synced": [], "plain": "line one\nline two", "instrumental": False}


@resp_mock.activate
def test_fetch_lyrics_reports_instrumental():
    resp_mock.add(resp_mock.GET, GET_URL, json=_record(synced=None, plain=None, instrumental=True))
    resp_mock.add(resp_mock.GET, SEARCH_URL, json=[])
    result = fetch_lyrics("Booker T. & the M.G.'s", "Green Onions")
    assert result["instrumental"] is True


@resp_mock.activate
def test_fetch_lyrics_returns_empty_on_miss():
    resp_mock.add(resp_mock.GET, GET_URL, status=404)
    resp_mock.add(resp_mock.GET, SEARCH_URL, json=[])
    assert fetch_lyrics("Nobody", "Nowhere") == {"synced": [], "plain": "", "instrumental": False}


@resp_mock.activate
def test_hits_are_cached_on_disk():
    resp_mock.add(resp_mock.GET, GET_URL, json=_record())
    fetch_lyrics("Queen", "Bohemian Rhapsody")
    lyrics.set_cache_path(lyrics._db_path)  # reopen the file, as after a restart
    fetch_lyrics("Queen", "Bohemian Rhapsody")
    assert len(resp_mock.calls) == 1


@resp_mock.activate
def test_misses_expire(monkeypatch):
    resp_mock.add(resp_mock.GET, GET_URL, status=404)
    resp_mock.add(resp_mock.GET, SEARCH_URL, json=[])
    fetch_lyrics("Nobody", "Nowhere")
    assert get_cached_lyrics("Nobody", "Nowhere") is not None

    real_time = time.time
    monkeypatch.setattr(lyrics.time, "time", lambda: real_time() + lyrics.MISS_TTL_S + 1)
    assert get_cached_lyrics("Nobody", "Nowhere") is None


@resp_mock.activate
def test_network_errors_are_not_cached():
    resp_mock.add(resp_mock.GET, GET_URL, body=requests.ConnectionError("down"))
    resp_mock.add(resp_mock.GET, SEARCH_URL, body=requests.ConnectionError("down"))
    assert fetch_lyrics("Queen", "Bohemian Rhapsody")["synced"] == []
    assert get_cached_lyrics("Queen", "Bohemian Rhapsody") is None


@resp_mock.activate
def test_search_retries_a_flaky_503(monkeypatch):
    monkeypatch.setattr(lyrics.time, "sleep", lambda s: None)
    resp_mock.add(resp_mock.GET, GET_URL, status=503)
    resp_mock.add(resp_mock.GET, SEARCH_URL, status=503)
    resp_mock.add(resp_mock.GET, SEARCH_URL, json=[_record()])
    assert len(fetch_lyrics("Queen", "Bohemian Rhapsody")["synced"]) == 4


@resp_mock.activate
def test_search_503_is_not_cached_as_a_miss(monkeypatch):
    monkeypatch.setattr(lyrics.time, "sleep", lambda s: None)
    resp_mock.add(resp_mock.GET, GET_URL, status=503)
    resp_mock.add(resp_mock.GET, SEARCH_URL, status=503)
    fetch_lyrics("Queen", "Bohemian Rhapsody")
    assert get_cached_lyrics("Queen", "Bohemian Rhapsody") is None

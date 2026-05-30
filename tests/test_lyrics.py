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

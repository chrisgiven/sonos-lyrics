import pytest

import lyrics


@pytest.fixture(autouse=True)
def isolated_lyrics_cache(tmp_path):
    """Every test gets its own empty SQLite lyrics cache."""
    lyrics.set_cache_path(str(tmp_path / "lyrics.db"))
    yield
    lyrics.set_cache_path(str(tmp_path / "unused.db"))

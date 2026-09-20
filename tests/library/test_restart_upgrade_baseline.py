"""Restart and upgrade from a released baseline.

One install's data survives an in-place upgrade and a second start: a settings
file in the pre-provider shape (the pre-split quality carrier, the retired
Atmos toggle, a custom album template) and an ownership database in the
baseline schema (before ``audio_type``), holding the same raw id for both
providers, a stereo and an Atmos copy, and a recorded file path per copy.
The launch keeps every user choice and file reference, and the second start
changes nothing. The one deliberate exception is an implausible pacing value
(seconds counted as albums by an older release): the one-time reset puts it
back on the default, and the test asserts that reset explicitly.

The settings side drives the app's own ``Settings`` startup class (read, the
run-once migrations, the write-back) against a baseline file; the baseline
schema below is the exact CREATE TABLE of the baseline release, and the
current store migrates it with its forward-compatible ALTERs.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from waves import config
from waves.config import Settings as LaunchSettings
from waves.config import SingletonMeta
from waves.constants import QualityTier
from waves.library.ownership import OwnershipStore
from waves.model.cfg import Settings as ModelSettings

pytestmark = pytest.mark.usefixtures("isolated_settings_migrations")

# The downloads table as the baseline release created it: no audio_type, no
# presence keys. The current store adds what is missing on open.
_BASELINE_DOWNLOADS = """CREATE TABLE downloads (
    track_id TEXT NOT NULL,
    path TEXT NOT NULL,
    quality_tier TEXT,
    quality_rank INTEGER NOT NULL DEFAULT -1,
    audio_mode TEXT,
    bit_depth INTEGER,
    sample_rate INTEGER,
    codecs TEXT,
    user_id TEXT,
    recorded_at INTEGER NOT NULL DEFAULT 0,
    requested_rank INTEGER NOT NULL DEFAULT -1,
    ceiling_rank INTEGER NOT NULL DEFAULT -1,
    degraded_tries INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (track_id, path)
)"""

_BASELINE_JSON = {
    "quality_audio": "LOSSLESS",
    "download_dolby_atmos": True,
    "download_base_path": "/music/waves",
    "format_album": "Custom/{album_artist}/{album_title}",
    "skip_existing": True,
    "metadata_replay_gain": False,
    "api_rate_limit_delay_sec": 900,
    "lyrics_embed": False,
    "metadata_cover_embed": False,
}


def _launch_settings(tmp_path, monkeypatch):
    """The app's own startup class over a settings file in tmp_path.

    ``Settings.__init__`` is read + the run-once migrations + the write-back;
    the singleton is reset around it so each call is a real launch, and the
    file path is patched so no test touches the shared config home.
    """
    monkeypatch.setattr(config, "path_file_settings", lambda: str(tmp_path / "settings.json"))
    SingletonMeta._instances.pop(LaunchSettings, None)
    launched = LaunchSettings()
    # Drop it again: a shared singleton left holding this test's file would
    # leak the baseline into every later test that asks for Settings().
    SingletonMeta._instances.pop(LaunchSettings, None)
    return launched.data


def test_baseline_settings_survive_the_upgrade_and_a_second_start(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(_BASELINE_JSON), encoding="utf-8")

    first = _launch_settings(tmp_path, monkeypatch)

    # Every user choice survives, in its upgraded spelling.
    assert first.tidal_quality_audio == QualityTier.LOSSLESS
    assert first.default_audio_type == "both"  # the retired Atmos toggle folded in
    assert first.download_base_path == "/music/waves"
    assert first.format_album == "Custom/{album_artist}/{album_title}"
    assert first.skip_existing is True
    assert first.metadata_replay_gain is True  # the one-time migration flips the old default on
    # The one deliberate reset: 900 s is an albums-era value, not a pause.
    assert first.api_rate_limit_delay_sec == ModelSettings().api_rate_limit_delay_sec
    # The shared lyrics/artwork toggles were copied into both provider mirrors.
    assert first.tidal_lyrics_embed is False and first.apple_lyrics_embed is False
    assert first.tidal_metadata_cover_embed is False and first.apple_metadata_cover_embed is False
    # The retired carrier never reaches disk again, and the launch saved.
    assert "quality_audio" not in json.loads(path.read_text(encoding="utf-8"))
    assert "tidal_quality_audio" in json.loads(path.read_text(encoding="utf-8"))

    # Second start: a fresh launch reads what the first wrote and changes
    # nothing, so the serialized file is byte-stable.
    second = _launch_settings(tmp_path, monkeypatch)
    assert second.to_json() == first.to_json()


def test_baseline_ownership_upgrades_without_losing_copies_or_ids(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    stereo = downloads / "10 - stereo.flac"
    atmos = downloads / "10 - atmos.m4a"
    apple = downloads / "apple 10.m4a"
    for copy in (stereo, atmos, apple):
        copy.write_bytes(b"\x00" * 16)

    db = tmp_path / "downloads.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(_BASELINE_DOWNLOADS)
    conn.executemany(
        "INSERT INTO downloads (track_id, path, quality_tier, quality_rank, audio_mode, recorded_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("10", str(stereo), "LOSSLESS", 2, "STEREO", 100),
            ("10", str(atmos), "HI_RES_LOSSLESS", 3, "DOLBY_ATMOS", 101),
            ("apple:10", str(apple), "LOSSLESS", 2, "STEREO", 102),
        ],
    )
    conn.commit()
    conn.close()

    store = OwnershipStore(str(db))
    store.set_roots(lambda: [str(downloads)])
    assert store.ownership_of("10")["path"] == str(atmos)  # highest rank first
    assert store.ownership_of("10", audio_type="stereo")["path"] == str(stereo)
    assert store.ownership_of("10", audio_type="atmos")["path"] == str(atmos)
    assert store.ownership_of("apple:10")["path"] == str(apple)
    assert store.ownership_of("10")["path"] != str(apple), "one provider's copy owned another's track"
    store.close()

    # The open backfilled the type column from the mode and namespaced the
    # bare id, once: the second start sees a current schema and current rows.
    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT path, audio_type FROM downloads"))
    ids = dict(conn.execute("SELECT path, track_id FROM downloads"))
    conn.close()
    assert rows[str(atmos)] == "atmos" and rows[str(stereo)] == "stereo"
    assert ids[str(stereo)] == "tidal:10"

    again = OwnershipStore(str(db))
    again.set_roots(lambda: [str(downloads)])
    assert again.ownership_of("10", audio_type="atmos")["path"] == str(atmos)
    assert again.ownership_of("10", audio_type="stereo")["path"] == str(stereo)
    assert again.ownership_of("apple:10")["path"] == str(apple)
    again.close()

    conn = sqlite3.connect(db)
    (count,) = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()
    conn.close()
    assert count == 3, "a restart duplicated rows"

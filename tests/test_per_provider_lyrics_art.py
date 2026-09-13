"""Per-provider lyrics/artwork + one tag template (issue #61).

Each provider keeps its own lyrics & artwork options inside its Providers
card; the engine reads the track's provider mirrors with the shared keys
as legacy fallback. The Metadata section holds the one tag template every
provider shares: Provider default writes what each provider supplies,
Custom omits the tag groups switched off. Lyrics and cover embedding are
not template tags: the per-provider embed toggles are their single source
of truth.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from waves.constants import CoverDimensions
from waves.model.cfg import (
    LYRICS_ART_KEYS,
    METADATA_TAG_FLAGS,
    Settings,
    metadata_tag_write,
    provider_setting,
)

pytestmark = pytest.mark.usefixtures("isolated_settings_migrations")


def test_mirrors_win_then_legacy_then_default():
    data = SimpleNamespace(tidal_lyrics_embed=True, lyrics_embed=False)
    assert provider_setting(data, "tidal", "lyrics_embed", False) is True
    assert provider_setting(data, "apple", "lyrics_embed", False) is False
    assert provider_setting(SimpleNamespace(), "tidal", "lyrics_embed", "dflt") == "dflt"
    assert provider_setting(None, "tidal", "lyrics_embed", "dflt") == "dflt"


def test_real_settings_resolve_both_mirrors():
    fresh = Settings()
    assert provider_setting(fresh, "tidal", "lyrics_file", False) is True
    assert provider_setting(fresh, "apple", "lyrics_ttml_file", False) is True
    assert provider_setting(fresh, "tidal", "metadata_cover_dimension", None) is CoverDimensions.PxORIGIN
    assert provider_setting(fresh, "apple", "cover_file_format", None) == "raw"


def test_every_mirrored_key_exists_on_both_providers():
    fresh = Settings()
    for base in LYRICS_ART_KEYS:
        assert hasattr(fresh, f"tidal_{base}"), base
        assert hasattr(fresh, f"apple_{base}"), base


def test_migration_copies_shared_values_into_both_mirrors_once():
    from waves.config import _migrate_settings

    data = Settings()
    data.lyrics_embed = True
    data.cover_file_format = "png"
    data.metadata_cover_dimension = CoverDimensions.Px640
    data.lyrics_art_per_provider_migrated = False
    assert _migrate_settings(data) is True
    assert data.tidal_lyrics_embed is True and data.apple_lyrics_embed is True
    assert data.tidal_cover_file_format == "png" and data.apple_cover_file_format == "png"
    assert data.tidal_metadata_cover_dimension is CoverDimensions.Px640
    assert data.lyrics_art_per_provider_migrated is True
    # Second run leaves divergent mirrors alone.
    data.apple_lyrics_embed = False
    _migrate_settings(data)
    assert data.tidal_lyrics_embed is True and data.apple_lyrics_embed is False


def test_template_writes_everything_by_default_and_honors_custom():
    data = Settings()
    for tag in METADATA_TAG_FLAGS:
        assert metadata_tag_write(data, tag) is True
        assert metadata_tag_write(None, tag) is True
    data.metadata_custom = True
    data.metadata_tag_isrc = False
    data.metadata_tag_bpm = False
    assert metadata_tag_write(data, "isrc") is False
    assert metadata_tag_write(data, "bpm") is False
    assert metadata_tag_write(data, "composer") is True


def _blank_flac(path):
    """A minimal tag-writable FLAC (magic + STREAMINFO, no comment block:
    mutagen adds one on save)."""
    import struct

    streaminfo = (
        struct.pack(">HH", 4096, 4096)
        + b"\x00" * 6
        + struct.pack(">Q", (44100 << 44) | (2 << 41) | (16 << 36))
        + b"\x00" * 16
    )
    path.write_bytes(b"fLaC" + bytes([(1 << 7) | 0]) + len(streaminfo).to_bytes(3, "big") + streaminfo)


def test_metadata_writer_omits_only_switched_off_groups(tmp_path):
    from mutagen.flac import FLAC

    from waves.metadata import Metadata

    src = tmp_path / "t.flac"

    def tags(**flags):
        _blank_flac(src)
        m = Metadata(
            path_file=src,
            target_upc={"FLAC": "UPC", "MP3": "UPC", "MP4": "UPC"},
            title="T",
            artists=["A"],
            albumartist=["A"],
            composer="C",
            isrc="I",
            copy_right="R",
            bpm=120,
            initial_key="8A",
            upc="123",
            **flags,
        )
        m.save()
        return {k.upper(): v for k, v in dict(FLAC(src).tags).items()}

    full = tags()
    assert full["COMPOSER"] == ["C"] and full["ISRC"] == ["I"] and full["BPM"] == ["120"]
    assert full["INITIALKEY"] == ["8A"] and full["UPC"] == ["123"] and full["COPYRIGHT"] == ["R"]
    partial = tags(write_isrc=False, write_bpm=False, write_copyright=False)
    assert "ISRC" not in partial and "BPM" not in partial and "COPYRIGHT" not in partial
    assert partial["COMPOSER"] == ["C"] and partial["UPC"] == ["123"]


def _schema():
    from tests.test_providers_settings_area import _schema_stub
    from waves.waves_ui.backend import WavesBridge

    return {s["id"]: s for s in WavesBridge.settingsSchema(_schema_stub())}


def _providers(schema):
    return {p["id"]: p for p in schema["providers"]["providers"]}


def test_bands_carry_the_mirrors_with_composites_and_gates():
    cards = _providers(_schema())
    tidal = {f["key"]: f for f in cards["providers_tidal"]["fields"]}
    apple = {f["key"]: f for f in cards["providers_apple"]["fields"]}
    # Lyrics file tiles carry their synced-only child on both cards.
    assert tidal["tidal_lyrics_file"]["child_key"] == "tidal_lyrics_file_synced_only"
    assert apple["apple_lyrics_file"]["child_key"] == "apple_lyrics_file_synced_only"
    # Cover size composites carry their own file size.
    assert tidal["tidal_metadata_cover_dimension"]["file_key"] == "tidal_metadata_cover_file_dimension"
    assert apple["apple_metadata_cover_dimension"]["file_key"] == "apple_metadata_cover_file_dimension"
    assert tidal["tidal_cover_album_file"]["child_key"] == "tidal_cover_single_track_file"
    # The LRCLIB gate references the provider's own switches, never shared keys.
    assert set(apple["apple_lyrics_prefer_lrclib"]["requires_any"]) == {
        "apple_lyrics_embed",
        "apple_lyrics_file",
        "apple_lyrics_ttml_file",
    }
    assert set(tidal["tidal_lyrics_prefer_lrclib"]["requires_any"]) == {
        "tidal_lyrics_embed",
        "tidal_lyrics_file",
        "tidal_lyrics_ttml_file",
    }
    # Cover format stays a dropdown with the honest raw label per provider.
    assert [o["value"] for o in apple["apple_cover_file_format"]["options"]] == ["jpg", "png", "raw"]
    assert "Apple only" in apple["apple_cover_file_format"]["options"][2]["label"]
    assert "TIDAL" in tidal["tidal_cover_file_format"]["options"][2]["label"]


def test_metadata_section_holds_the_template_and_no_embed_toggles():
    from tests.test_providers_settings_area import _schema_stub
    from waves.waves_ui.backend import WavesBridge

    stub = _schema_stub()
    stub.settingsSchema = WavesBridge.settingsSchema.__get__(stub, type(stub))
    stub._factory_default_values = WavesBridge._factory_default_values.__get__(stub, type(stub))
    sections = {s["id"]: s for s in WavesBridge.settingsSchema(stub)}
    assert sections["metadata"]["group"] == "Metadata"
    keys = [f["key"] for f in sections["metadata"]["fields"]]
    assert keys == [
        "mark_explicit",
        "clean_album_artist",
        "metadata_replay_gain",
        "metadata_write_url",
        "metadata_target_upc",
        "initial_key_format",
        "metadata_custom",
        "metadata_tag_composer",
        "metadata_tag_copyright",
        "metadata_tag_isrc",
        "metadata_tag_bpm",
        "metadata_tag_initial_key",
        "metadata_tag_upc",
    ]
    # Lyrics/cover embedding lives only in the Providers cards now: no key
    # here may duplicate those toggles.
    for key in keys:
        assert "lyrics" not in key and "cover" not in key
    by_key = {f["key"]: f for f in sections["metadata"]["fields"]}
    for tag in (
        "metadata_tag_composer",
        "metadata_tag_copyright",
        "metadata_tag_isrc",
        "metadata_tag_bpm",
        "metadata_tag_initial_key",
        "metadata_tag_upc",
    ):
        assert by_key[tag]["depends_on"] == "metadata_custom"
    # The moved template keys left Advanced.
    advanced = [f["key"] for f in sections["advanced"]["fields"]]
    for moved in ("metadata_replay_gain", "metadata_write_url", "metadata_target_upc", "initial_key_format"):
        assert moved not in advanced
    # Factory reset reaches the mirrors and the template through the schema.
    values = stub._factory_default_values()
    assert values["tidal_lyrics_file"] is True and values["apple_lyrics_ttml_file"] is True
    assert values["metadata_custom"] is False and values["metadata_tag_isrc"] is True


def test_chooser_defaults_read_the_row_provider_mirrors():
    from waves.waves_ui import backend
    from waves.waves_ui.backend import WavesBridge

    stub = SimpleNamespace()
    stub.settings = SimpleNamespace(
        data=SimpleNamespace(
            tidal_lyrics_embed=True,
            apple_lyrics_embed=False,
            tidal_cover_album_file=False,
            apple_cover_album_file=True,
        )
    )
    stub._chooser_provider_of = WavesBridge._chooser_provider_of.__get__(stub, type(stub))
    stub._chooser_is_collection_kind = WavesBridge._chooser_is_collection_kind.__get__(stub, type(stub))
    stub._chooser_default_tier_word = lambda pid: "HI-RES"
    stub._chooser_default_audio = lambda: "stereo"
    stub._chooser_atmos_only = lambda mid, kind: False
    stub._chooser_tier_entries = lambda pid: []
    stub._get_apple_enabled = lambda: False
    stub._psetting = WavesBridge._psetting.__get__(stub, type(stub))
    stub.chooserDefaults = WavesBridge.chooserDefaults.__get__(stub, type(stub))
    tidal = stub.chooserDefaults("t1", "track")
    assert tidal["lyricsEmbed"] is True and tidal["coverFile"] is False
    apple = stub.chooserDefaults("apple:1", "track")
    assert apple["lyricsEmbed"] is False and apple["coverFile"] is True
    assert backend is not None

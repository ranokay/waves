"""Best quality out of the box (issue #59).

Fresh installs fetch the highest rung on both providers, keep the finest
lyrics sidecars (.lrc everywhere, verbatim .ttml on Apple), and save
original-quality artwork in its original container (raw: true master bytes
on Apple, plain jpg on TIDAL, which has no master sidecar). Quality
dropdowns state each rung as an "Up to" ceiling with bitrate or bit
depth / sample rate, so the choice reads as a fidelity promise.

Existing installs are never migrated onto these: changing a stored choice
under the user would be a silent reset, so the new values only flow to
configs that never set the keys (see test_the_default_is_what_a_fresh_install_gets).
"""

from __future__ import annotations

from waves.constants import CoverDimensions
from waves.model.cfg import Settings
from waves.waves_ui.backend import _ENUM_LABELS


def test_fresh_install_defaults_to_the_highest_rung_on_both_providers():
    fresh = Settings()
    assert fresh.tidal_quality_audio == "HI_RES_LOSSLESS"
    assert fresh.apple_quality_audio == "HI_RES_LOSSLESS"


def test_fresh_install_keeps_the_finest_lyrics_and_art():
    fresh = Settings()
    assert fresh.lyrics_file is True
    assert fresh.lyrics_word_timed is True
    assert fresh.lyrics_ttml_file is True
    assert fresh.lyrics_embed is False
    assert fresh.metadata_cover_dimension is CoverDimensions.PxORIGIN
    assert fresh.metadata_cover_file_dimension == "follow"
    assert fresh.cover_file_format == "raw"


def test_quality_dropdowns_state_up_to_ceilings():
    tidal = _ENUM_LABELS["tidal_quality_audio"]
    assert tidal["LOW"] == "Low · Up to 96 Kbps"
    assert tidal["HIGH"] == "High · Up to 320 Kbps"
    assert tidal["LOSSLESS"] == "Lossless · Up to 16-bit / 44.1 kHz"
    assert tidal["HI_RES_LOSSLESS"] == "Max · Hi-Res · Up to 24-bit / 192 kHz"
    apple = _ENUM_LABELS["apple_quality_audio"]
    assert apple["HIGH"] == "High · Up to 256 Kbps (AAC)"
    assert apple["LOSSLESS"] == "Lossless · Up to 16-bit / 44.1 kHz (ALAC)"
    assert apple["HI_RES_LOSSLESS"] == "Max · Hi-Res · Up to 24-bit / 192 kHz (ALAC)"
    for labels in (tidal, apple):
        assert all("Up to" in label for label in labels.values())

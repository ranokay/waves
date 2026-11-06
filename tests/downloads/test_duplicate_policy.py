"""One duplicate decision for both engines, and readable Keep-both names."""

from __future__ import annotations

from downloads.fakes import make_download, make_track

from waves.library.placement import (
    PROTECTED_REASON,
    RETAINED_REASON,
    ExistingCopy,
    decide_placement,
    keep_both_name,
)


def _existing(**changes) -> ExistingCopy:
    values = {
        "path": "/music/Song.flac",
        "owned": True,
        "same_item": True,
        "same_version": True,
        "unchanged": True,
        "current": True,
        "minimum_met": True,
    }
    values.update(changes)
    return ExistingCopy(**values)


def test_keep_existing_skips_a_current_copy_and_retains_one_below_the_minimum():
    assert decide_placement("keep_existing", _existing()).action == "skip"

    retained = decide_placement("keep_existing", _existing(current=False, minimum_met=False), minimum_required=True)

    assert retained.action == "retain"
    assert retained.reason == RETAINED_REASON


def test_keep_existing_best_available_still_re_fetches_a_stale_copy():
    decision = decide_placement("keep_existing", _existing(current=False, minimum_met=False))

    assert decision.action == "download"


def test_replace_owned_replaces_only_a_proven_owned_unchanged_copy():
    replaced = decide_placement("replace_owned", _existing())
    protected = decide_placement("replace_owned", _existing(unchanged=None))

    assert replaced.action == "replace" and replaced.overwrite
    assert protected.action == "keep_both"
    assert protected.reason == PROTECTED_REASON
    assert protected.readable_suffix


def test_refresh_own_keeps_the_legacy_identity_answer_without_the_digest_rule():
    decision = decide_placement("refresh_own", _existing(unchanged=None, owned=False))

    assert decision.action == "replace" and decision.overwrite


def test_keep_both_always_lands_beside_with_the_readable_suffix():
    decision = decide_placement("keep_both", _existing())

    assert decision.action == "keep_both" and decision.readable_suffix


def test_keep_both_name_is_readable_and_counts_collisions(tmp_path):
    destination = tmp_path / "Song.flac"
    destination.write_bytes(b"existing")

    first = keep_both_name(
        destination,
        provider="Apple Music",
        quality="HI-RES LOSSLESS",
        audio_type="stereo",
    )
    assert first is not None
    assert first.name == "Song [Apple Music HI-RES LOSSLESS stereo].flac"

    first.write_bytes(b"copy")
    second = keep_both_name(
        destination,
        provider="Apple Music",
        quality="HI-RES LOSSLESS",
        audio_type="stereo",
    )
    assert second is not None
    assert second.name == "Song [Apple Music HI-RES LOSSLESS stereo] [2].flac"


def test_engine_claims_the_recorded_path_only_for_a_proven_unchanged_copy(tmp_path):
    from waves.metadata.digest import audio_digest

    destination = tmp_path / "Song.ogg"
    destination.write_bytes(b"old audio")
    digest = audio_digest(destination)
    dl = make_download(tmp_path)
    dl._duplicate_policy = "replace_owned"
    dl._ownership_of = lambda *_a, **_k: {
        "path": str(destination),
        "quality_rank": 2,
        "audio_digest": digest,
        "audio_type": "stereo",
    }

    picked, _claim = dl._claim_destination(destination, "42", media=make_track("42"))

    assert picked == destination

    destination.write_bytes(b"user replaced the audio")
    picked, _claim = dl._claim_destination(destination, "42", media=make_track("42"))

    assert picked != destination
    assert picked.name.startswith("Song [")


def test_keep_both_naming_keeps_the_collection_folder_and_track_prefix(tmp_path):
    folder = tmp_path / "Album"
    folder.mkdir()
    first = folder / "01 Song.flac"
    first.write_bytes(b"existing")

    second = keep_both_name(first, provider="Tidal", quality="LOSSLESS", audio_type="stereo")

    assert second is not None
    assert second.parent == first.parent
    assert second.name.startswith("01 Song [Tidal LOSSLESS stereo]")


def test_refresh_own_replaces_an_untagged_legacy_copy_without_a_row(tmp_path):
    """Skip existing off keeps its historical answer: an untagged file at the
    destination is this track's own, even when no ownership row exists."""
    destination = tmp_path / "Song.ogg"
    destination.write_bytes(b"legacy untagged copy")
    dl = make_download(tmp_path, skip_existing=False)
    dl._duplicate_policy = "refresh_own"
    dl._ownership_of = lambda *_a, **_k: None

    picked, claim = dl._claim_destination(destination, "42", media=make_track("42"))

    assert picked == destination
    assert claim is not None
    assert dl._tls.placement.action == "replace"


def test_keep_both_name_honours_a_claimed_full_path(tmp_path):
    first = tmp_path / "Song.flac"
    first.write_bytes(b"existing")

    claimed = keep_both_name(
        first,
        provider="Tidal",
        quality="LOSSLESS",
        audio_type="stereo",
        taken={str(tmp_path / "Song [Tidal LOSSLESS stereo].flac")},
    )

    assert claimed is not None
    assert claimed.name == "Song [Tidal LOSSLESS stereo] [2].flac"

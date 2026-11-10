"""Keep existing + a required minimum keeps the copy and says so.

A below-minimum copy must not be forced into a fetch that overwrites it with an
equal-or-lower delivery, and the outcome is retained/skipped, never fulfilled.
"""

from __future__ import annotations

from types import SimpleNamespace

from waves.desktop.backend import _TrackedDownload


def _gate(*, owned, claim=None, strategy="minimum_required", target=3):
    dl = _TrackedDownload.__new__(_TrackedDownload)
    dl._ownership_of = (lambda tid: dict(owned)) if owned else (lambda tid: None)
    dl._target_rank = target
    dl._quality_strategy = strategy
    dl._skip_existing_base = True
    dl._library_claim = claim
    dl._force_redownload = False
    dl.settings = SimpleNamespace(data=SimpleNamespace(default_audio_type="stereo"))
    return dl


def _track(tid=42):
    return SimpleNamespace(id=tid, track_num=1, volume_num=1, duration=180, waves_identity_id=None)


def test_keep_existing_below_the_minimum_is_retained_without_a_fetch():
    owned = {"path": "/music/Song.flac", "quality_rank": 2, "quality_tier": "LOSSLESS"}

    verdict, detail = _gate(owned=owned)._claim_decision(_track())

    assert verdict == "retain"
    assert "minimum" in detail["reason"].lower()


def test_best_available_keeps_todays_re_fetch_of_a_stale_copy():
    owned = {"path": "/music/Song.flac", "quality_rank": 2, "quality_tier": "LOSSLESS"}

    assert _gate(owned=owned, strategy="best_available")._claim_decision(_track())[0] == "force"


def test_a_bulk_claim_below_the_minimum_is_not_a_skip():
    claim = {"local_class": "lossless"}

    assert _gate(owned=None, claim=lambda media: claim)._claim_decision(_track())[0] is None


def test_a_bulk_claim_meeting_the_minimum_still_skips():
    claim = {"local_class": "hires"}

    assert _gate(owned=None, claim=lambda media: claim)._claim_decision(_track())[0] == "skip"


def test_a_ceiling_capped_copy_still_reports_retained():
    owned = {
        "path": "/music/Song.flac",
        "quality_rank": 2,
        "quality_tier": "LOSSLESS",
        "ceiling_rank": 2,
    }
    media = _track()
    media.media_metadata_tags = ["LOSSLESS"]

    verdict, _detail = _gate(owned=owned)._claim_decision(media)

    assert verdict == "retain"


def test_a_settled_degraded_copy_still_reports_retained():
    owned = {
        "path": "/music/Song.flac",
        "quality_rank": 2,
        "quality_tier": "LOSSLESS",
        "ceiling_rank": 3,
        "degraded_tries": 2,
    }

    verdict, _detail = _gate(owned=owned)._claim_decision(_track())

    assert verdict == "retain"


def test_an_atmos_copy_below_the_minimum_is_retained_not_skipped():
    owned = {
        "path": "/music/Song.m4a",
        "quality_rank": 1,
        "quality_tier": "HIGH",
        "audio_type": "atmos",
    }
    media = _track()
    media.audio_modes = ["DOLBY_ATMOS"]
    dl = _gate(owned=owned)
    dl._audio_type = "atmos"

    verdict, detail = dl._claim_decision(media)

    assert verdict == "retain"
    assert "minimum" in detail["reason"].lower()


def test_the_job_note_names_kept_and_kept_both():
    from waves.desktop.backend import _kept_note

    assert _kept_note(2, 1) == " (2 tracks kept, 1 track kept both)"
    assert _kept_note(0, 0) == ""


def test_a_tierless_copy_is_not_below_minimum():
    owned = {"path": "/music/Song.mp4", "quality_rank": -1}

    verdict, _detail = _gate(owned=owned)._claim_decision(_track())

    assert verdict == "skip"

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

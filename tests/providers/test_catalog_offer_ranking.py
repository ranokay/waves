from dataclasses import replace

import pytest

from waves.constants import QualityTier
from waves.metadata.catalog_identity import CatalogResolution, MatchState
from waves.providers.catalog_offers import (
    AvailabilityEvidence,
    CatalogOffer,
    DeliveryFacts,
    EvidenceState,
    OfferConstraints,
    choose_offer,
    compare_quality,
    satisfies,
)


def test_lossless_ranks_depth_before_rate_and_equates_flac_alac():
    flac = DeliveryFacts(
        tier=QualityTier.HI_RES_LOSSLESS, audio_type="stereo", codec="flac", bit_depth=24, sample_rate=48000
    )
    alac = DeliveryFacts(
        tier=QualityTier.HI_RES_LOSSLESS, audio_type="stereo", codec="alac", bit_depth=16, sample_rate=192000
    )
    assert compare_quality(flac, alac) == 1
    assert (
        compare_quality(
            flac, DeliveryFacts(tier=flac.tier, audio_type="stereo", codec="alac", bit_depth=24, sample_rate=48000)
        )
        == 0
    )


def test_unknown_resolution_and_incomparable_lossy_profiles_do_not_improve():
    assert (
        compare_quality(DeliveryFacts(codec="flac"), DeliveryFacts(codec="alac", bit_depth=24, sample_rate=192000))
        is None
    )
    assert (
        compare_quality(
            DeliveryFacts(codec="aac", profile="lc", bitrate=320000),
            DeliveryFacts(codec="aac", profile="he", bitrate=256000),
        )
        is None
    )


def test_aac_he_v2_aliases_have_one_neutral_comparison():
    alias = DeliveryFacts(audio_type="stereo", codec="mp4a.40.29", bitrate=256000)
    neutral = DeliveryFacts(audio_type="stereo", codec="aac", profile="he-v2", bitrate=256000)
    assert alias == neutral
    assert compare_quality(alias, neutral) == 0


def test_constraints_precede_quality_and_never_relax_mix_or_family():
    ask = OfferConstraints(tier=QualityTier.LOSSLESS, audio_type="stereo", required_codec="flac")
    assert not satisfies(DeliveryFacts(tier=QualityTier.HIGH, audio_type="stereo", codec="aac"), ask)
    assert not satisfies(DeliveryFacts(tier=QualityTier.LOSSLESS, audio_type="atmos", codec="flac"), ask)
    assert not satisfies(DeliveryFacts(tier=QualityTier.LOSSLESS, audio_type="stereo", codec="alac"), ask)


def offer(pid, fact, *, state=EvidenceState.AVAILABLE, match=MatchState.HIGH_CONFIDENCE, ask=None):
    return CatalogOffer(
        pid,
        f"{pid}:1",
        "track",
        CatalogResolution("origin:1", match),
        ask or OfferConstraints(tier=QualityTier.LOSSLESS),
        AvailabilityEvidence(probed=(fact,), state=state),
        readiness="ready",
    )


def lossless(depth=24, rate=96000, codec="flac"):
    return DeliveryFacts(
        tier=QualityTier.HI_RES_LOSSLESS, audio_type="stereo", codec=codec, bit_depth=depth, sample_rate=rate
    )


def test_quality_improvement_and_explicit_provider_tie_order():
    origin = offer("origin", lossless(16, 44100))
    other = offer("other", lossless())
    assert choose_offer((origin, other), origin_id="origin:1").provider_id == "other"
    origin = offer("origin", lossless(codec="alac"))
    assert choose_offer((origin, other), origin_id="origin:1").provider_id == "origin"
    assert (
        choose_offer((origin, other), origin_id="origin:1", provider_priority=("other", "origin")).provider_id
        == "other"
    )


def test_dual_ranking_requires_comparable_non_degrading_facts_for_both_families():
    ask = OfferConstraints(tier=QualityTier.LOSSLESS, audio_type="both")
    atmos = DeliveryFacts(tier=QualityTier.HIGH, audio_type="atmos", codec="eac3", profile="joc", bitrate=768000)

    def dual(pid, stereo, surround):
        candidate = offer(pid, stereo, ask=ask)
        return replace(candidate, evidence=replace(candidate.evidence, probed=(stereo, surround)))

    origin = dual("origin", lossless(16, 44100), atmos)
    better = dual("other", lossless(), atmos)
    assert choose_offer((origin, better), origin_id="origin:1").provider_id == "other"
    for surround in (replace(atmos, bitrate=640000), replace(atmos, bitrate=None)):
        candidate = dual("other", lossless(), surround)
        assert choose_offer((origin, candidate), origin_id="origin:1").provider_id == "origin"
    equal = dual("other", lossless(16, 44100), atmos)
    assert choose_offer((origin, equal), origin_id="origin:1", provider_priority=("other",)).provider_id == "other"
    partial = replace(better, evidence=replace(better.evidence, probed=(lossless(),)))
    assert choose_offer((origin, partial), origin_id="origin:1").provider_id == "origin"


@pytest.mark.parametrize(
    "state",
    [
        EvidenceState.UNKNOWN,
        EvidenceState.CHECKING,
        EvidenceState.STALE,
        EvidenceState.FAILED,
        EvidenceState.UNAVAILABLE,
    ],
)
def test_advertised_ceiling_cannot_beat_demonstrated_origin(state):
    origin, other = offer("origin", lossless()), offer("other", lossless(32, 192000), state=state)
    other = replace(other, evidence=replace(other.evidence, advertised=(lossless(32, 192000),)))
    assert choose_offer((origin, other), origin_id="origin:1", provider_priority=("other",)).provider_id == "origin"


@pytest.mark.parametrize("match", [MatchState.USER_CONFIRMED, MatchState.AMBIGUOUS, MatchState.UNRESOLVED])
def test_manual_or_weak_identity_never_gets_automatic_rank(match):
    assert (
        choose_offer(
            (offer("origin", lossless(16, 44100)), offer("other", lossless(), match=match)), origin_id="origin:1"
        ).provider_id
        == "origin"
    )


def test_unknown_origin_missing_resolution_and_pins_retain_origin():
    origin = offer("origin", lossless(), state=EvidenceState.UNKNOWN)
    assert choose_offer((origin, offer("other", lossless())), origin_id="origin:1").provider_id == "origin"
    origin = offer("origin", lossless())
    assert choose_offer((origin, offer("other", lossless(rate=None))), origin_id="origin:1").provider_id == "origin"
    pinned = replace(origin.selected, provider_pin="origin")
    assert (
        choose_offer(
            (replace(origin, selected=pinned), offer("other", lossless(32, 192000), ask=pinned)), origin_id="origin:1"
        ).provider_id
        == "origin"
    )


def test_minimum_and_exact_facts_filter_before_ranking_and_best_accepts_lower_lossless():
    low = lossless(16, 44100)
    assert satisfies(low, OfferConstraints(tier=QualityTier.HI_RES_LOSSLESS))
    assert not satisfies(
        replace(low, tier=QualityTier.LOSSLESS),
        OfferConstraints(tier=QualityTier.HI_RES_LOSSLESS, quality_strategy="minimum_required"),
    )
    assert not satisfies(low, OfferConstraints(tier=QualityTier.LOSSLESS, minimum_sample_rate=96000))
    assert not satisfies(lossless(rate=None), OfferConstraints(tier=QualityTier.LOSSLESS, minimum_sample_rate=44100))


def test_lossy_bitrate_compares_only_equal_codec_and_profile():
    a = DeliveryFacts(tier=QualityTier.HIGH, audio_type="stereo", codec="aac", profile="lc", bitrate=320000)
    assert compare_quality(a, replace(a, bitrate=256000)) == 1
    assert compare_quality(a, replace(a, profile="he")) is None
    assert compare_quality(a, replace(a, codec="mp3")) is None


def test_video_resolution_ranks_only_after_explicit_hdr_codec_and_fps_constraints():
    ask = OfferConstraints(video_height=720, video_codec="hevc", video_hdr="hdr", video_max_fps=60)
    high = DeliveryFacts(codec="hevc", height=1080, width=1920, hdr=True, frame_rate=60)
    low = replace(high, height=720, width=1280, frame_rate=30)
    assert satisfies(high, ask, video=True) and satisfies(low, ask, video=True)
    assert compare_quality(high, low, video=True) == 1
    for wrong in (
        replace(high, codec="h264"),
        replace(high, hdr=False),
        replace(high, frame_rate=120),
        replace(high, hdr=None),
    ):
        assert not satisfies(wrong, ask, video=True)

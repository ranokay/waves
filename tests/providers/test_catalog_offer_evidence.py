from __future__ import annotations

import base64
import json
from dataclasses import replace
from time import time
from types import SimpleNamespace

import pytest
from providers.fakes import BareProvider

from waves.constants import QualityTier
from waves.desktop.providers.catalog_identity import CatalogSelection
from waves.desktop.providers.catalog_offers import OfferEvidenceCache, collect_offers
from waves.desktop.providers.lifecycle import ProviderContexts
from waves.metadata.catalog_identity import CatalogIdentity, CatalogLookup
from waves.model.download_policy import DownloadPolicies
from waves.providers.base import AudioType, Capability
from waves.providers.catalog_offers import (
    AvailabilityEvidence,
    DeliveryFacts,
    EvidenceState,
    OfferConstraints,
    OfferPresence,
)
from waves.providers.tidal_offers import manifest_facts


class OfferProvider(BareProvider):
    identity_kinds = frozenset({"track", "album"})
    capabilities = frozenset({Capability.CATALOG, Capability.DOWNLOAD})
    audio_types = frozenset({AudioType.STEREO})

    def __init__(self, pid):
        self.id = pid
        self.context = "us/account/runtime-v1"
        self.enabled = True
        self.calls = 0
        self.on_probe = lambda: None
        self.on_identity = lambda: None
        self.evidence = AvailabilityEvidence(
            probed=(
                DeliveryFacts(
                    tier=QualityTier.LOSSLESS, audio_type="stereo", codec="flac", bit_depth=24, sample_rate=96000
                ),
            ),
            state=EvidenceState.AVAILABLE,
        )

    def catalog_identity_context(self):
        return (self.context,)

    def availability_context(self):
        return (self.context, str(self.enabled))

    def catalog_identity(self, kind, raw_id):
        self.on_identity()
        return CatalogIdentity(
            f"{self.id}:{raw_id}",
            kind,
            title="Song",
            artist="Artist",
            identifier="USABC1200001",
            duration_ms=180000,
            explicit=False,
            version="",
            release_title="Album",
            release_version="",
        )

    def catalog_candidates(self, origin):
        return CatalogLookup((self.catalog_identity(origin.kind, "2"),))

    def probe_availability(self, identity, ask):
        self.calls += 1
        self.on_probe()
        return self.evidence


def bridge(*providers):
    return SimpleNamespace(
        providers={p.id: p for p in providers},
        settings=SimpleNamespace(data=SimpleNamespace(download_policies=DownloadPolicies())),
        _provider_contexts=ProviderContexts(),
        _provider_readiness_probes={
            p.id: lambda p=p: p.readiness(enabled=p.enabled, signed_in=True) for p in providers
        },
    )


def collect(b, **kwargs):
    return collect_offers(
        b,
        (CatalogSelection("track", "origin:1"),),
        provider_ids=("other",),
        ask=kwargs.pop("ask", OfferConstraints(tier=QualityTier.LOSSLESS)),
        request_id=kwargs.pop("request_id", "request"),
        current=kwargs.pop("current", lambda: True),
        **kwargs,
    )[0]


def test_four_quality_facts_and_presence_are_independent_neutral_values():
    a, b = OfferProvider("origin"), OfferProvider("other")
    b.evidence = replace(b.evidence, advertised=(DeliveryFacts(tier=QualityTier.HI_RES_LOSSLESS),))
    payload = collect(
        bridge(a, b), presence=lambda identity: OfferPresence(owned=False, library_present=True)
    ).presentation()[0]
    assert payload["advertised"][0]["sample_rate"] is None
    assert payload["probed"][0]["sample_rate"] == 96000
    assert payload["selected"]["tier"] == "LOSSLESS"
    assert payload["delivered"] == [] and payload["owned"] is False and payload["library_present"] is True
    json.dumps(payload)


@pytest.mark.parametrize("change", ["origin", "target", "request", "runtime", "capability", "disabled", "matching"])
def test_queued_publication_discards_context_and_identity_after_worker_returns(change):
    a, b = OfferProvider("origin"), OfferProvider("other")
    host = bridge(a, b)
    active = True
    snapshot = collect(host, current=lambda: active)
    if change == "origin":
        host._provider_contexts.revoke(a.id)
    elif change == "target":
        host._provider_contexts.revoke(b.id)
    elif change == "runtime":
        b.context = "gb/account/runtime-v2"
    elif change == "capability":
        b.capabilities = frozenset({Capability.CATALOG})
    elif change == "disabled":
        b.enabled = False
    elif change == "matching":
        host.settings.data.download_policies.shared = replace(
            host.settings.data.download_policies.shared, matching="release"
        )
    else:
        active = False
    payload = snapshot.presentation()[0]
    assert payload["evidence_state"] == "stale"
    assert payload["probed"] == [] and not payload["automatic_eligible"]
    if change in ("target", "runtime", "capability", "disabled"):
        assert snapshot.presentation()[1]["evidence_state"] == "available"


def test_probe_change_is_discarded_and_never_cached():
    a, b = OfferProvider("origin"), OfferProvider("other")
    host = bridge(a, b)
    b.on_probe = lambda: host._provider_contexts.revoke(b.id)
    cache = OfferEvidenceCache()
    assert collect(host, cache=cache).presentation()[0]["evidence_state"] == "stale"
    b.on_probe = lambda: None
    assert collect(host, cache=cache).presentation()[0]["evidence_state"] == "available"
    assert b.calls == 2


@pytest.mark.parametrize("change", ["constraints", "identity", "request", "context", "epoch", "expiry"])
def test_cache_reuses_only_current_request_and_invalidation_dimensions(change):
    a, b = OfferProvider("origin"), OfferProvider("other")
    now = time()
    host, cache = bridge(a, b), OfferEvidenceCache(clock=lambda: now)
    collect(host, cache=cache)
    collect(host, cache=cache)
    assert b.calls == 1
    extra = {}
    if change == "constraints":
        extra["ask"] = OfferConstraints(tier=QualityTier.HI_RES_LOSSLESS)
    elif change == "identity":
        original = b.catalog_identity
        b.catalog_identity = lambda kind, raw_id: replace(original(kind, raw_id), duration_ms=180001)
    elif change == "request":
        extra["request_id"] = "another-request"
    elif change == "context":
        b.context = "gb/account2/runtime-v2"
    elif change == "epoch":
        host._provider_contexts.revoke(b.id)
    else:
        now += 120
    collect(host, cache=cache, **extra)
    assert b.calls == 2


def test_source_failure_setup_and_unknown_do_not_poison_other_provider():
    a, b = OfferProvider("origin"), OfferProvider("other")

    def fail():
        raise RuntimeError("private-path secret-token")

    b.on_probe = fail
    payload = collect(bridge(a, b)).presentation()
    assert payload[0]["evidence_state"] == "failed" and "secret" not in str(payload)
    assert payload[1]["evidence_state"] == "available"
    b.enabled = False
    payload = collect(bridge(a, b)).presentation()[0]
    assert payload["readiness"] == "disabled" and b.calls == 1


def test_opt_in_demand_bound_and_unresolved_identity_prevent_probes():
    a, b = OfferProvider("origin"), OfferProvider("other")
    host = bridge(a, b)
    with pytest.raises(ValueError, match="opt-in"):
        collect(host, trigger="auto")
    assert a.calls == b.calls == 0
    b.catalog_candidates = lambda origin: CatalogLookup(complete=False)
    assert collect(host).presentation()[0]["match_state"] == "unresolved"
    assert b.calls == 0
    with pytest.raises(ValueError, match="bound"):
        collect_offers(
            host,
            (CatalogSelection("track", "origin:1"),) * 65,
            provider_ids=(b.id,),
            ask=OfferConstraints(),
            request_id="x",
            current=lambda: True,
        )


def test_repeated_entries_keep_each_origins_publication_guard():
    a, b = OfferProvider("origin"), OfferProvider("other")
    host = bridge(a, b)
    results = collect_offers(
        host,
        (CatalogSelection("track", "origin:1"), CatalogSelection("track", "other:2")),
        provider_ids=(a.id, b.id),
        ask=OfferConstraints(tier=QualityTier.LOSSLESS),
        request_id="x",
        current=lambda: True,
    )
    host._provider_contexts.revoke(a.id)
    assert all(p["evidence_state"] == "stale" for p in results[0].presentation())
    assert results[1].presentation()[1]["evidence_state"] == "available"


def test_raw_manifest_missing_values_do_not_inherit_sdk_defaults_or_urls():
    raw = {
        "audioQuality": "LOSSLESS",
        "audioMode": "STEREO",
        "manifestMimeType": "application/vnd.tidal.bts",
        "manifest": base64.b64encode(
            json.dumps({"codecs": "FLAC", "urls": ["https://secret/media"]}).encode()
        ).decode(),
    }
    (fact,) = manifest_facts(raw)
    assert fact.sample_rate is None and fact.bit_depth is None
    assert fact.codec == "flac" and "secret" not in str(fact)
    raw.update(bitDepth=24, sampleRate=96000)
    (fact,) = manifest_facts(raw)
    assert (fact.bit_depth, fact.sample_rate) == (24, 96000)


def test_dash_manifest_codec_profile_and_rate_are_actual_facts():
    xml = '<MPD><Period><AdaptationSet audioSamplingRate="48000"><Representation codecs="mp4a.40.2" bandwidth="256000"/></AdaptationSet></Period></MPD>'
    (fact,) = manifest_facts(
        {"manifestMimeType": "application/dash+xml", "manifest": base64.b64encode(xml.encode()).decode()}
    )
    assert (fact.codec, fact.profile, fact.sample_rate, fact.bitrate, fact.bit_depth) == (
        "aac",
        "lc",
        48000,
        256000,
        None,
    )


@pytest.mark.parametrize("data,mime", [(b"{", "bts"), (b"[]", "bts"), (b"<MPD>", "dash+xml")])
def test_malformed_manifest_preserves_unknown_evidence(data, mime):
    assert manifest_facts({"manifestMimeType": mime, "manifest": base64.b64encode(data).decode()}) == ()
    assert manifest_facts({"manifestMimeType": mime, "manifest": "invalid base64"}) == ()


def test_bad_dash_attribute_keeps_independent_known_rendition_facts():
    xml = '<MPD><Period><AdaptationSet><Representation codecs="mp4a.40.2" audioSamplingRate="bad" bandwidth="256000"/><Representation codecs="mp4a.40.2" audioSamplingRate="48000" bandwidth="bad"/></AdaptationSet></Period></MPD>'
    facts = manifest_facts({"manifestMimeType": "dash+xml", "manifest": base64.b64encode(xml.encode()).decode()})
    assert [(fact.sample_rate, fact.bitrate) for fact in facts] == [(None, 256000), (48000, None)]
    assert all(fact.codec == "aac" and fact.profile == "lc" for fact in facts)


def test_native_probe_preserves_advertising_when_manifest_is_malformed():
    from waves.providers.tidal_offers import probe

    def request(method, path, params=None):
        payload = (
            {"id": 1, "audioQuality": "HI_RES_LOSSLESS"}
            if path == "tracks/1"
            else {"manifest": "invalid base64", "manifestMimeType": "bts"}
        )
        return SimpleNamespace(json=lambda: payload)

    session = SimpleNamespace(request=SimpleNamespace(request=request))
    evidence = probe(session, CatalogIdentity("tidal:1", "track"), OfferConstraints(tier=QualityTier.LOSSLESS))
    assert evidence.state == EvidenceState.UNKNOWN and evidence.probed == ()
    assert evidence.advertised[0].tier == QualityTier.HI_RES_LOSSLESS


def test_encrypted_manifest_does_not_establish_delivery_availability():
    assert not manifest_facts(
        {
            "manifestMimeType": "application/vnd.tidal.bts",
            "manifest": base64.b64encode(
                b'{"codecs":"FLAC","encryptionType":"OLD_AES","urls":["https://private/media"]}'
            ).decode(),
        }
    )


def test_native_tidal_publication_stamp_does_not_repeat_package_lookup(monkeypatch):
    import waves.providers.tidal as module

    session = SimpleNamespace(
        user=SimpleNamespace(id="account"), country_code="US", config=SimpleNamespace(openapi_v2_location="v2")
    )
    provider = module.TidalProvider(SimpleNamespace(session=session))
    captured = provider.availability_context()

    def forbidden(*args):
        raise AssertionError("Publication must not read installed package metadata")

    monkeypatch.setattr(module, "version", forbidden)
    assert provider.availability_context() == captured


@pytest.mark.parametrize(
    "tier,strategy,expected",
    [
        (QualityTier.LOSSLESS, "best_available", "HI_RES_LOSSLESS"),
        (QualityTier.LOSSLESS, "minimum_required", "LOSSLESS"),
        (QualityTier.LOW, "best_available", "HIGH"),
    ],
)
def test_real_tidal_probe_reads_only_raw_item_and_manifest_without_quality_mutation(tier, strategy, expected):
    from threading import Lock

    from waves.providers.tidal import TidalProvider

    calls = []

    def request(method, path, params=None):
        calls.append((path, params))
        payload = (
            {"id": 1, "audioQuality": "HI_RES_LOSSLESS"}
            if path == "tracks/1"
            else {
                "audioQuality": "LOSSLESS",
                "audioMode": "STEREO",
                "manifestMimeType": "application/vnd.tidal.bts",
                "manifest": base64.b64encode(b'{"codecs":"FLAC","urls":["https://private/media"]}').decode(),
            }
        )
        return SimpleNamespace(json=lambda: payload)

    session = SimpleNamespace(request=SimpleNamespace(request=request), audio_quality="LOW")
    provider = TidalProvider(SimpleNamespace(session=session, stream_lock=Lock()))
    evidence = provider.probe_availability(
        CatalogIdentity("tidal:1", "track"), OfferConstraints(tier=tier, quality_strategy=strategy)
    )
    assert len(calls) == 2 and calls[1][1]["audioquality"] == expected
    assert session.audio_quality == "LOW"
    assert evidence.advertised[0].tier == "HI_RES_LOSSLESS"
    assert evidence.probed[0].tier == "LOSSLESS" and evidence.probed[0].bit_depth is None
    assert "private" not in str(evidence)


def test_real_apple_metadata_probe_never_calls_media_or_invents_ceiling(monkeypatch):
    from waves.providers.apple import AppleProvider
    from waves.providers.apple.engines import EngineFacts

    class Catalog:
        storefront = "us"
        calls = 0

        async def _amp_request(self, uri, params):
            self.calls += 1
            return {
                "data": [
                    {
                        "id": "2",
                        "type": "songs",
                        "attributes": {"audioTraits": ["lossless", "hi-res-lossless", "atmos"]},
                    }
                ]
            }

    catalog = Catalog()
    provider = AppleProvider(catalog=catalog)
    provider.engine_facts_probe = lambda: EngineFacts(
        enabled=True,
        cookies_ready=True,
        wrapper_ready=True,
        fetch_ready=True,
        protocol_compatible=True,
        wrapper_runtime_ready=True,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Media action must be explicit")

    monkeypatch.setattr(provider, "resolve_stream", forbidden)
    identity = CatalogIdentity("apple:2", "track")
    evidence = provider.probe_availability(identity, OfferConstraints(tier=QualityTier.LOSSLESS))
    assert catalog.calls == 1 and evidence.state == "unknown" and not evidence.probed
    assert all(fact.bit_depth is None and fact.sample_rate is None and not fact.codec for fact in evidence.advertised)
    assert {fact.tier for fact in evidence.advertised} >= {QualityTier.LOSSLESS, QualityTier.HI_RES_LOSSLESS}
    ask = OfferConstraints(tier=QualityTier.LOSSLESS)
    live = provider.readiness(enabled=True)
    provider.engine_facts_probe = lambda: EngineFacts(
        enabled=True,
        cookies_ready=True,
        wrapper_ready=False,
        fetch_ready=True,
        protocol_compatible=False,
        wrapper_runtime_ready=False,
    )
    assert provider.offer_readiness(identity, ask, live).state == "setup_required"


def test_broken_readiness_and_context_do_not_abort_healthy_provider():
    a, b, broken = OfferProvider("origin"), OfferProvider("other"), OfferProvider("broken")

    def fail(*args, **kwargs):
        raise RuntimeError("failure")

    broken.readiness = fail
    broken.availability_context = fail
    host = bridge(a, b, broken)
    payload = collect_offers(
        host,
        (CatalogSelection("track", "origin:1"),),
        provider_ids=(broken.id, b.id),
        ask=OfferConstraints(tier=QualityTier.LOSSLESS),
        request_id="x",
        current=lambda: True,
    )[0].presentation()
    assert payload[1]["evidence_state"] == "available"
    assert broken.calls == 0


@pytest.mark.parametrize(
    "change",
    [
        "provider",
        "library",
        "library_publication",
        "library_scanning",
        "library_partial",
        "library_reconciled",
        "library_status",
    ],
)
def test_bridge_request_preserves_gui_hop_guard_and_close_revokes_publication(change):
    from waves.desktop.backend import WavesBridge

    class Signal:
        def __init__(self):
            self.events = []

        def emit(self, *args):
            self.events.append(args)

    class Pool:
        def start(self, worker):
            self.worker = worker

    a, b = OfferProvider("origin"), OfferProvider("other")
    host = bridge(a, b)
    host._catalog_offer_generation = 0
    host._library_gen = 0
    host._library_stamp = 0
    host._catalog_offer_cache = OfferEvidenceCache()
    host._catalogOffersEvent = Signal()
    host.catalogOffersLoaded = Signal()
    host.threadpool = Pool()
    host._ownership = SimpleNamespace(ownership_of=lambda *args, **kwargs: None)
    host._catalog_offer_presence = WavesBridge._catalog_offer_presence.__get__(host)
    for method in (
        "providerDescriptor",
        "chooserDefaults",
        "_provider_meta",
        "_chooser_provider_of",
        "_chooser_default_tier_word",
        "_chooser_default_audio",
        "_chooser_tier_entries",
        "_chooser_atmos_only",
        "_psetting",
    ):
        setattr(host, method, getattr(WavesBridge, method).__get__(host))
    request = WavesBridge.requestCatalogOffers(host, "origin:1", "track", "LOSSLESS", "stereo")
    assert not a.calls and not b.calls
    host.threadpool.worker.run()
    (event,) = host._catalogOffersEvent.events[0]

    def forbidden():
        raise AssertionError("Queued publication must not run live readiness probes")

    host._provider_readiness_probes = {a.id: forbidden, b.id: forbidden}
    if change == "provider":
        host._provider_contexts.revoke(b.id)
    elif change == "library":
        host._library_gen += 1
    elif change == "library_publication":
        host._library_stamp += 1
    else:
        field, value = {
            "library_scanning": ("_library_index_building", True),
            "library_partial": ("_library_scan_partial", True),
            "library_reconciled": ("_library_listing_reconciled", True),
            "library_status": ("_library_scan_status", "error"),
        }[change]
        setattr(host, field, value)
    WavesBridge._on_catalog_offers(host, event)
    loaded_id, payload = host.catalogOffersLoaded.events[0]
    assert loaded_id == request and payload[1]["evidence_state"] == "stale"
    assert payload[0]["evidence_state"] == ("available" if change == "provider" else "stale")
    WavesBridge.cancelCatalogOffers(host, request)
    WavesBridge._on_catalog_offers(host, event)
    assert len(host.catalogOffersLoaded.events) == 1


def test_dual_download_probes_separate_stereo_and_atmos_constraints():
    a, b = OfferProvider("origin"), OfferProvider("other")
    b.audio_types = frozenset({AudioType.STEREO, AudioType.ATMOS})
    calls = []

    def probe(identity, ask):
        calls.append(ask)
        fact = (
            b.evidence.probed[0]
            if ask.audio_type == "stereo"
            else DeliveryFacts(tier=QualityTier.HIGH, audio_type="atmos", codec="eac3")
        )
        return AvailabilityEvidence(probed=(fact,), state=EvidenceState.AVAILABLE)

    b.probe_availability = probe
    payload = collect(bridge(a, b), ask=OfferConstraints(tier=QualityTier.LOSSLESS, audio_type="both")).presentation()[
        0
    ]
    assert [(ask.audio_type, ask.tier) for ask in calls] == [
        ("stereo", QualityTier.LOSSLESS),
        ("atmos", QualityTier.HIGH),
    ]
    assert payload["readiness"] == "ready" and payload["evidence_state"] == "available"
    assert {fact["audio_type"] for fact in payload["probed"]} == {"stereo", "atmos"}
    assert "Stereo: Manifest" in payload["summary"] and "Atmos: Manifest" in payload["summary"]
    assert payload["selected"]["audio_type"] == "both"


def test_engine_readiness_is_scoped_without_requiring_a_provider_pin():
    a, b = OfferProvider("origin"), OfferProvider("other")
    observed = []
    for provider in (a, b):
        provider.offer_readiness = lambda identity, ask, live, provider=provider: (
            observed.append((provider.id, ask.engine_pin)) or live.for_operation(Capability.DOWNLOAD)
        )
    collect(bridge(a, b), ask=OfferConstraints(engine_pin="chosen-engine"))
    assert observed == [("other", ""), ("origin", "chosen-engine")]
    observed.clear()
    collect(bridge(a, b), ask=OfferConstraints(provider_pin="other", engine_pin="chosen-engine"))
    assert observed == [("other", "chosen-engine"), ("origin", "")]


def test_ownership_sdk_numeric_defaults_are_not_published_as_delivered_evidence():
    from waves.desktop.backend import WavesBridge

    host = SimpleNamespace(
        _ownership=SimpleNamespace(
            ownership_of=lambda *args, **kwargs: {
                "quality_tier": "LOSSLESS",
                "audio_type": "stereo",
                "codecs": "FLAC",
                "bit_depth": 16,
                "sample_rate": 44100,
            }
        )
    )
    presence = WavesBridge._catalog_offer_presence(host, CatalogIdentity("tidal:1", "track"), "stereo")
    assert presence.owned is True
    assert presence.delivered[0].codec == "flac"
    assert presence.delivered[0].bit_depth is None and presence.delivered[0].sample_rate is None


def test_ownership_is_available_during_setup_without_polluting_delivery_evidence():
    a, b = OfferProvider("origin"), OfferProvider("other")
    b.offer_readiness = lambda identity, ask, live: __import__(
        "waves.providers.base", fromlist=["OperationReadiness"]
    ).OperationReadiness(Capability.DOWNLOAD, "setup_required")
    payload = collect(
        bridge(a, b),
        presence=lambda identity: OfferPresence(
            owned=True, library_present=True, delivered=(DeliveryFacts(tier=QualityTier.HIGH, codec="aac"),)
        ),
    ).presentation()[0]
    assert payload["readiness"] == "setup_required" and payload["owned"] is True
    assert payload["delivered"][0]["codec"] == "aac" and not payload["probed"] and not b.calls


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("library_present", [None, False, True])
def test_catalog_presence_distinguishes_download_ownership_from_scanned_library(owned, library_present):
    from waves.desktop.backend import WavesBridge
    from waves.metadata.matching import track_key

    rec = {"quality_tier": "LOSSLESS", "audio_type": "stereo", "codecs": "FLAC"} if owned else None
    index = None if library_present is None else {}
    if library_present:
        index = {
            track_key("Recording", "Artist"): [
                {"id": "/library/Release", "album": "Release", "album_year": "2020", "length": 180, "codec": "flac"}
            ]
        }
    host = SimpleNamespace(
        _ownership=SimpleNamespace(ownership_of=lambda *args, **kwargs: rec), _library_track_index=index
    )
    identity = CatalogIdentity(
        "apple:2", "track", title="Recording", artist="Artist", release_title="Release", release_date="2020-01-01"
    )
    presence = WavesBridge._catalog_offer_presence(host, identity, "stereo")
    assert presence.owned is owned
    assert presence.library_present is library_present
    assert bool(presence.delivered) is owned
    assert "/library/Release" not in str(presence)


@pytest.mark.parametrize("difference", [{"album_year": "1997"}, {"length": 270}, {"explicit": 1}])
def test_catalog_library_presence_does_not_promote_an_unproven_recording(difference):
    from waves.desktop.backend import WavesBridge
    from waves.metadata.matching import track_key

    host = SimpleNamespace(
        _ownership=SimpleNamespace(ownership_of=lambda *args, **kwargs: None),
        _library_track_index={
            track_key("Recording", "Artist"): [
                {"id": "/library/Release", "album": "Release", "album_year": "2020", "length": 180, **difference}
            ]
        },
    )
    identity = CatalogIdentity(
        "apple:2",
        "track",
        title="Recording",
        artist="Artist",
        release_title="Release",
        release_date="2020-01-01",
        duration_ms=180000,
        explicit=False,
    )
    presence = WavesBridge._catalog_offer_presence(host, identity, "stereo")
    assert presence.owned is False
    assert presence.library_present is None


@pytest.mark.parametrize("release_version", ["Deluxe Edition", "Remastered", "2015 Remaster"])
@pytest.mark.parametrize("same_edition", [False, True])
def test_catalog_library_presence_preserves_separate_release_version(release_version, same_edition):
    from waves.desktop.backend import WavesBridge
    from waves.metadata.matching import track_key

    album = f"Release ({release_version})" if same_edition else "Release"
    host = SimpleNamespace(
        _ownership=SimpleNamespace(ownership_of=lambda *args, **kwargs: None),
        _library_track_index={
            track_key("Recording", "Artist"): [
                {"id": "/library/Release", "album": album, "album_year": "2020", "length": 180}
            ]
        },
    )
    identity = CatalogIdentity(
        "tidal:1",
        "track",
        title="Recording",
        artist="Artist",
        release_title="Release",
        release_version=release_version,
        release_date="2020-01-01",
        duration_ms=180000,
    )
    presence = WavesBridge._catalog_offer_presence(host, identity, "stereo")
    assert presence.owned is False
    assert presence.library_present is (True if same_edition else None)


@pytest.mark.parametrize("version", ["Live", "Acoustic"])
@pytest.mark.parametrize("same_recording", [False, True])
def test_catalog_library_presence_preserves_separate_recording_version(version, same_recording):
    from waves.desktop.backend import WavesBridge
    from waves.metadata.matching import track_key

    title = f"Recording ({version})" if same_recording else "Recording"
    host = SimpleNamespace(
        _ownership=SimpleNamespace(ownership_of=lambda *args, **kwargs: None),
        _library_track_index={
            track_key(title, "Artist"): [
                {"id": "/library/Release", "album": "Release", "album_year": "2020", "length": 180}
            ]
        },
    )
    identity = CatalogIdentity(
        "tidal:1",
        "track",
        title="Recording",
        version=version,
        artist="Artist",
        release_title="Release",
        release_date="2020-01-01",
        duration_ms=180000,
    )
    presence = WavesBridge._catalog_offer_presence(host, identity, "stereo")
    assert presence.owned is False
    assert presence.library_present is same_recording


@pytest.mark.parametrize(
    "state,miss",
    [
        ({}, False),
        ({"_library_index_building": True}, None),
        ({"_library_scan_partial": True}, None),
        ({"_library_scan_partial": True, "_library_listing_reconciled": True}, False),
        ({"_library_scan_status": "unset"}, None),
        ({"_library_scan_status": "error"}, None),
        ({"_library_scan_status": "missing"}, None),
        ({"_library_scan_status": "unreadable"}, None),
    ],
)
@pytest.mark.parametrize("found", [False, True])
def test_catalog_library_misses_require_a_complete_trusted_index(state, miss, found):
    from waves.desktop.backend import WavesBridge
    from waves.metadata.matching import track_key

    index = {}
    if found:
        index[track_key("Recording", "Artist")] = [
            {"id": "/library/Release", "album": "Release", "album_year": "2020", "length": 180}
        ]
    host = SimpleNamespace(
        _ownership=SimpleNamespace(ownership_of=lambda *args, **kwargs: None),
        _library_track_index=index,
        **state,
    )
    identity = CatalogIdentity(
        "tidal:1", "track", title="Recording", artist="Artist", release_title="Release", release_date="2020-01-01"
    )
    presence = WavesBridge._catalog_offer_presence(host, identity, "stereo")
    assert presence.owned is False
    assert presence.library_present is (True if found else miss)

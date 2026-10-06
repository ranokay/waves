from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from waves.desktop.providers.catalog_identity import CatalogSelection, resolve_selected
from waves.desktop.providers.lifecycle import ProviderContexts
from waves.metadata.catalog_identity import CatalogIdentity, resolve_candidates
from waves.model.download_policy import DownloadPolicies, FulfillmentPolicy
from waves.providers import Capability, TidalProvider
from waves.providers.apple import AppleProvider
from waves.providers.base import Provider


def _apple_track(raw_id="2", **changes):
    attrs = {
        "name": "Song",
        "artistName": "Artist",
        "albumName": "Album",
        "isrc": "USABC1200001",
        "durationInMillis": 180123,
        "contentRating": "clean",
        "trackNumber": 1,
        "discNumber": 1,
    }
    attrs.update(changes)
    return {"id": raw_id, "type": "songs", "attributes": attrs}


def _apple_album():
    return {
        "id": "20",
        "type": "albums",
        "attributes": {
            "name": "Album",
            "artistName": "Artist",
            "upc": "123456789012",
            "releaseDate": "2020-01-01",
            "trackCount": 1,
            "contentRating": "clean",
        },
        "relationships": {"tracks": {"data": [_apple_track()]}},
    }


class AppleCatalog:
    storefront = "us"

    def __init__(self):
        self.calls = []
        self.track = _apple_track()
        self.album = _apple_album()
        self.matches = [{"id": "2"}]
        self.next = None
        self.extra_tracks = {}
        self.extra_albums = {}
        self.include_meta = True
        self.filter_matches = None
        self.on_lookup = lambda: None

    async def _amp_request(self, uri, params):
        self.calls.append((uri, params))
        if "/songs/" in uri:
            raw_id = uri.rsplit("/", 1)[-1]
            resource = deepcopy(self.track if raw_id == "2" else self.extra_tracks[raw_id])
            resource["relationships"] = {"albums": {"data": [deepcopy(self.album)]}}
            return {"data": [resource]}
        if "/albums/" in uri:
            raw_id = uri.rsplit("/", 1)[-1]
            return {"data": [deepcopy(self.album if raw_id == "20" else self.extra_albums[raw_id])]}
        if uri.endswith("/search"):
            return {"results": {"songs": {"data": self.matches}}}
        self.on_lookup()
        response = {"data": self.matches, "next": self.next}
        if self.include_meta:
            field = "upc" if "filter[upc]" in params else "isrc"
            response["meta"] = {"filters": {field: {params[f"filter[{field}]"]: self.filter_matches or self.matches}}}
        return response


class TidalRequest:
    def __init__(self):
        self.calls = []
        self.track = {
            "id": 1,
            "title": "Song",
            "artist": {"name": "Artist"},
            "isrc": "USABC1200001",
            "duration": 180.123,
            "version": None,
            "explicit": False,
            "trackNumber": 1,
            "volumeNumber": 1,
            "album": {"id": 10, "title": "Album"},
        }
        self.album = {
            "id": 10,
            "title": "Album",
            "artist": {"name": "Artist"},
            "upc": "123456789012",
            "releaseDate": "2020-01-01",
            "numberOfTracks": 1,
            "version": None,
            "explicit": False,
        }
        self.matches = [{"id": "1"}]
        self.next = None

    def request(self, method, path, params=None, base_url=None):
        self.calls.append((path, params, base_url))
        resources = {
            "tracks/1": self.track,
            "albums/10": self.album,
            "albums/10/tracks": {"items": [self.track]},
            "tracks": {"data": self.matches, "links": {"next": self.next}},
            "albums": {"data": [{"id": "10"}]},
            "search/tracks": {"items": self.matches},
        }
        if path not in resources:
            raise AssertionError(f"Unexpected catalog path: {path}")
        return SimpleNamespace(json=lambda: deepcopy(resources[path]))


def _providers():
    request = TidalRequest()
    session = SimpleNamespace(
        request=request,
        config=SimpleNamespace(openapi_v2_location="https://openapi.tidal.com/v2/"),
        check_login=lambda: True,
    )
    tidal = TidalProvider(SimpleNamespace(session=session))
    catalog = AppleCatalog()
    apple = AppleProvider(catalog=catalog, engines=())
    return tidal, apple, request, catalog


def _bridge(*providers, policy="recording"):
    policies = DownloadPolicies(shared=FulfillmentPolicy(matching=policy))
    return SimpleNamespace(
        providers={p.id: p for p in providers},
        settings=SimpleNamespace(data=SimpleNamespace(download_policies=policies)),
        _provider_contexts=ProviderContexts(),
        _provider_readiness_probes={p.id: (lambda p=p: p.readiness(enabled=True, signed_in=True)) for p in providers},
    )


def _resolve(bridge, entries=None, provider_ids=("apple",), current=lambda: True):
    return resolve_selected(
        bridge, entries or (CatalogSelection("track", "1"),), provider_ids=provider_ids, current=current
    )


def test_real_provider_bridge_contract_keeps_millisecond_facts_and_separate_ids():
    tidal, apple, request, catalog = _providers()
    bridge = _bridge(tidal, apple)
    result = _resolve(bridge)[0].offers[0].resolution
    assert result.automatic_eligible
    assert result.origin_id == "tidal:1"
    assert result.candidates[0].identity.media_id == "apple:2"
    assert result.candidates[0].identity.duration_ms == 180123
    assert catalog.calls[0][1]["filter[isrc]"] == "USABC1200001"
    assert len(catalog.calls) == 2
    assert len(request.calls) == 2
    assert not bridge.settings.data.download_policies.choose_best_provider


def test_strict_edition_reads_the_persisted_policy_without_another_store():
    tidal, apple, _, catalog = _providers()
    catalog.album["attributes"]["name"] = "Compilation"
    assert _resolve(_bridge(tidal, apple))[0].offers[0].resolution.automatic_eligible
    assert not _resolve(_bridge(tidal, apple, policy="release"))[0].offers[0].resolution.automatic_eligible


@pytest.mark.parametrize("attrs", [{"contentRating": None}, {"durationInMillis": None}, {"isrc": ""}])
def test_raw_missing_apple_facts_are_not_display_defaults(attrs):
    tidal, apple, _, catalog = _providers()
    catalog.track["attributes"].update(attrs)
    result = _resolve(_bridge(tidal, apple))[0].offers[0].resolution
    assert not result.automatic_eligible
    assert result.candidates[0].missing


def test_provider_neutral_lookup_works_in_reverse_and_stops_at_continuation():
    tidal, apple, request, _ = _providers()
    origin = apple.catalog_identity("track", "2")
    lookup = tidal.catalog_candidates(origin)
    assert resolve_candidates(origin, lookup).automatic_eligible
    assert request.calls[-3][1]["filter[isrc]"] == "USABC1200001"
    request.next = "another-page"
    assert not resolve_candidates(origin, tidal.catalog_candidates(origin)).automatic_eligible


def test_real_album_adapter_contract_requires_complete_ordered_tracks():
    tidal, apple, _, catalog = _providers()
    catalog.matches = [{"id": "20"}]
    entries = (CatalogSelection("album", "10"),)
    assert _resolve(_bridge(tidal, apple), entries)[0].offers[0].resolution.automatic_eligible
    catalog.album["relationships"]["tracks"]["next"] = "/continuation"
    result = _resolve(_bridge(tidal, apple), entries)[0].offers[0].resolution
    assert not result.automatic_eligible
    assert "ordered track list" in " ".join(result.explanations)


def test_repeated_selected_entries_survive_without_catalog_pagination():
    tidal, apple, _, catalog = _providers()
    entry = CatalogSelection("track", "1")
    results = _resolve(_bridge(tidal, apple), (entry, entry))
    assert len(results) == 2
    assert all(result.offers[0].resolution.automatic_eligible for result in results)
    assert len(catalog.calls) == 4
    assert all("cursor" not in str(params) for _, params in catalog.calls)


def test_disabled_or_unsupported_providers_and_video_never_receive_lookups():
    tidal, apple, _, catalog = _providers()
    bridge = _bridge(tidal, apple)
    bridge._provider_readiness_probes["apple"] = lambda: apple.readiness(enabled=False)
    assert not _resolve(bridge)[0].offers
    assert not catalog.calls
    assert not _resolve(bridge, (CatalogSelection("video", "1"),))[0].offers
    assert not catalog.calls
    lookup = apple.catalog_candidates(CatalogIdentity("tidal:video", "video"))
    assert not lookup.candidates
    assert not catalog.calls


@pytest.mark.parametrize("changed", ["origin", "target", "selection", "policy", "storefront", "catalog_epoch"])
def test_context_changes_discard_late_confirmable_catalog_evidence(changed):
    tidal, apple, _, catalog = _providers()
    bridge = _bridge(tidal, apple)
    selected = True

    def change():
        nonlocal selected
        if changed == "origin":
            bridge._provider_contexts.revoke("tidal")
        elif changed == "target":
            bridge._provider_contexts.revoke("apple")
        elif changed == "policy":
            bridge.settings.data.download_policies.shared = FulfillmentPolicy(matching="release")
        elif changed == "storefront":
            catalog.storefront = "gb"
        elif changed == "catalog_epoch":
            apple.invalidate_catalog_context()
        else:
            selected = False

    catalog.on_lookup = change
    result = _resolve(bridge, current=lambda: selected)[0]
    assert not result.offers or not result.offers[0].resolution.candidates


def test_provider_failure_is_isolated_and_sdk_secrets_never_enter_explanations():
    tidal, apple, _, _catalog = _providers()

    class Broken(Provider):
        id = "broken"
        identity_kinds = frozenset({"track"})
        capabilities = frozenset({Capability.CATALOG})
        public_operations = capabilities
        catalog_candidates = lambda self, origin: (_ for _ in ()).throw(RuntimeError("secret=token"))

    # Reuse the real provider's complete abstract seam, changing only the
    # transport boundary and identity of this additional capable provider.
    broken = TidalProvider.__new__(TidalProvider)
    broken.id = "broken"
    broken.catalog_candidates = Broken.catalog_candidates.__get__(broken)
    broken.readiness = lambda **kwargs: tidal.readiness(signed_in=True)
    broken.catalog_identity_context = lambda: ()
    bridge = _bridge(tidal, apple, broken)
    results = _resolve(bridge, provider_ids=("broken", "apple"))[0].offers
    assert results[0].resolution.state == "unresolved"
    assert "token" not in str(results[0].resolution)
    assert results[1].resolution.automatic_eligible


def test_missing_identifier_uses_bounded_manual_candidates_without_auto_promotion():
    tidal, apple, request, catalog = _providers()
    request.track["isrc"] = ""
    result = _resolve(_bridge(tidal, apple))[0].offers[0].resolution
    assert not result.automatic_eligible
    assert result.confirm("apple:2").state == "user_confirmed"
    assert catalog.calls[0][0].endswith("/search")
    assert catalog.calls[0][1]["limit"] == 10


def test_context_bound_is_checked_before_network_work():
    tidal, apple, request, catalog = _providers()
    with pytest.raises(ValueError, match="bound"):
        _resolve(_bridge(tidal, apple), (CatalogSelection("track", "1"),) * 65)
    assert not request.calls and not catalog.calls


def test_apple_filter_metadata_exposes_hidden_identifier_collision():
    tidal, apple, _, catalog = _providers()
    catalog.filter_matches = [{"id": "2"}, {"id": "3"}]
    catalog.extra_tracks["3"] = _apple_track("3", contentRating="explicit")
    result = _resolve(_bridge(tidal, apple))[0].offers[0].resolution
    assert result.state == "ambiguous"
    assert not result.automatic_eligible
    assert {item.identity.media_id for item in result.candidates} == {"apple:2", "apple:3"}
    assert "collision" in " ".join(result.explanations)


def test_apple_missing_filter_metadata_cannot_certify_an_exhaustive_lookup():
    tidal, apple, _, catalog = _providers()
    catalog.include_meta = False
    result = _resolve(_bridge(tidal, apple))[0].offers[0].resolution
    assert not result.automatic_eligible
    assert result.candidates


def test_separate_tidal_album_version_blocks_original_master_substitution():
    tidal, apple, request, _ = _providers()
    request.album["version"] = "2015 Remaster"
    result = _resolve(_bridge(tidal, apple))[0].offers[0].resolution
    assert not result.automatic_eligible
    assert "remaster" in " ".join(result.explanations)


@pytest.mark.parametrize("selected,stage", [(False, "stamp"), (True, "stamp"), (True, "readiness")])
def test_another_provider_context_failure_never_aborts_healthy_results(selected, stage):
    tidal, apple, _, _ = _providers()
    broken = TidalProvider.__new__(TidalProvider)
    broken.id = "broken"

    def fail(*_args, **_kwargs):
        raise RuntimeError("unavailable")

    broken.catalog_identity_context = fail
    broken.readiness = fail if stage == "readiness" else lambda **kwargs: tidal.readiness(signed_in=True)
    bridge = _bridge(tidal, apple, broken)
    provider_ids = ("broken", "apple") if selected else ("apple",)
    result = _resolve(bridge, provider_ids=provider_ids)[0]
    assert result.offers[-1].provider_id == "apple"
    assert result.offers[-1].resolution.automatic_eligible


def test_tidal_storefront_change_invalidates_request_snapshot():
    tidal, apple, _request, catalog = _providers()
    tidal._tidal.session.country_code = "US"
    catalog.on_lookup = lambda: setattr(tidal._tidal.session, "country_code", "GB")
    result = _resolve(_bridge(tidal, apple))[0]
    assert not result.offers


def test_tidal_album_with_unsupported_video_entries_is_incomplete():
    tidal, apple, request, catalog = _providers()
    request.album["numberOfVideos"] = 1
    catalog.matches = [{"id": "20"}]
    result = _resolve(_bridge(tidal, apple), (CatalogSelection("album", "10"),))[0].offers[0].resolution
    assert not result.automatic_eligible


def test_apple_upc_metadata_cannot_hide_a_conflicting_edition():
    tidal, apple, _, catalog = _providers()
    catalog.matches = [{"id": "20"}]
    catalog.filter_matches = [{"id": "20"}, {"id": "21"}]
    different = deepcopy(catalog.album)
    different["id"] = "21"
    different["attributes"]["name"] = "Album (Deluxe)"
    catalog.extra_albums["21"] = different
    result = _resolve(_bridge(tidal, apple), (CatalogSelection("album", "10"),))[0].offers[0].resolution
    assert not result.automatic_eligible
    assert len(result.candidates) == 2


@pytest.mark.parametrize("missing", ["track", "album"])
def test_missing_native_tidal_version_facts_do_not_become_plain_master_evidence(missing):
    tidal, apple, request, _ = _providers()
    (request.track if missing == "track" else request.album).pop("version")
    result = _resolve(_bridge(tidal, apple))[0].offers[0].resolution
    assert not result.automatic_eligible
    assert result.candidates[0].missing

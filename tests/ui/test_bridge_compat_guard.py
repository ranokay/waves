"""The bridge's compat guard: the import and monkeypatch surface stays alive.

WHAT THIS FENCES OFF
--------------------
``backend.py`` imports its provider-surface helpers back by name, and the
suite patches module globals on ``backend`` (``_image``, ``name_builder_title``,
``_fmt_duration``, ...). A mixin moved to a new module binds its own globals,
so a patch on ``backend._image`` would silently stop taking effect once the
calling row builder moves, and the suite could go vacuous without failing.

Every future bridge-split PR runs this file unmodified: the frozen lists fail
when a name is removed, the identity check fails when an alias is shadowed by
a same-named definition, and the behavioral tests fail when a patch no longer
reaches the slot or row it used to reach.

This guard never asserts which file defines a method, only that the
``backend.<name>`` reference tests and shipped code use resolves and behaves.
"""

from __future__ import annotations

from types import SimpleNamespace

from support.provider_fakes import StubProvider, stub_bridge

from waves.desktop import backend, bridge_surfaces
from waves.desktop.backend import WavesBridge
from waves.providers import Capability

# The helpers backend.py imports back by name from bridge_surfaces
# (backend.py's ``from .bridge_surfaces import (...)`` block). Removing one
# breaks ``backend._name`` references; redefining one in backend shadows the
# import and silently forks the monkeypatch target.
_BRIDGE_SURFACE_ALIASES = (
    "_APPLE_UNAVAILABLE_STATUS",
    "_CHOOSER_KINDS",
    "_FAVOURITES_CATEGORIES",
    "_LIBRARY_VIEW_LABELS",
    "_SEARCH_SECTIONS",
    "_apple_status",
    "_begin_login",
    "_browse_nav",
    "_fmt_duration",
    "_is_provider_surface_pref",
    "_lib_disk_key",
    "_lib_key",
    "_library_file_row",
    "_library_files_view",
    "_my_music_empty",
    "_my_music_sources",
    "_provider_card",
    "_provider_descriptor_dict",
    "_provider_light",
    "_provider_lights",
    "_provider_logos",
    "_provider_registry",
    "_provider_session_field",
    "_provider_sign_out",
    "_record_in_library",
    "_session_logged_in",
    "_source_provider",
    "_source_rows",
)

# Module globals the suite patches on ``backend`` today (``rg
# 'setattr\(backend[^)]*"' tests``), each read as a bare global by a row
# builder or gate in backend.py. Moving a caller without keeping the
# ``backend._name`` reference turns those patches vacuous.
_PATCH_TARGETS = (
    "_IS_MACOS",
    "_ProgressSignals",
    "_all_playlist_items",
    "_artist_id",
    "_artist_popularity",
    "_artist_roles",
    "_artists_list",
    "_atmos_only",
    "_factory_wipe_art_cache",
    "_has_atmos",
    "_headless_platform",
    "_image",
    "_offers_both",
    "_preview_http",
    "_preview_seg_registered",
    "_primary_artist_name",
    "_quality_label",
    "_track_count",
    "OwnershipStore",
    "format_path_media",
    "name_builder_artist",
    "name_builder_title",
    "path_config_base",
)

# Names tests import from backend, plus what shipped code imports
# (app.py reads ``_ART_CACHE_DIR``). Removing or renaming one breaks the
# importer; the frozen list keeps the rename honest.
_PUBLIC_IMPORTS = (
    "_ART_CACHE_DIR",
    "_FACTORY_WIPE_LOG_PATTERNS",
    "_FACTORY_WIPE_SUBDIRS",
    "_FIRST_RUN_OVERRIDES",
    "_MergeRec",
    "_TEMPLATE_TOKENS",
    "_TrackedDownload",
    "_align_edition",
    "_as_member_of",
    "_build_merge_plan",
    "_collapse_album_editions",
    "_collection_incomplete_reason",
    "_copy_is_current",
    "_delivers_atmos",
    "_edition_base_key",
    "_explicit_sides",
    "_merge_rec_title",
    "_norm_track_title",
    "_seed_merge_registry",
    "_split_explicit_editions",
    "_strip_edition_quals",
    "WavesBridge",
    "atmos_file_template",
)


def test_frozen_backend_names_still_exist():
    missing = [
        name for name in (*_BRIDGE_SURFACE_ALIASES, *_PATCH_TARGETS, *_PUBLIC_IMPORTS) if not hasattr(backend, name)
    ]
    assert not missing, f"backend lost names tests or shipped code use: {missing!r}"


def test_surface_aliases_are_not_shadowed():
    forked = [name for name in _BRIDGE_SURFACE_ALIASES if getattr(backend, name) is not getattr(bridge_surfaces, name)]
    assert not forked, (
        f"backend redefined these bridge_surfaces helpers instead of importing them: {forked!r} "
        "(a patch on backend.<name> would no longer reach bridge_surfaces callers, or vice versa)"
    )


def test_patched_surface_helpers_reach_the_slots(monkeypatch):
    """A patch on ``backend._name`` still drives the QML-facing slot.

    Each slot below is a thin wrapper around the bare module global; a split
    that moves the slot without the import-back turns the patched global into
    a dead knob while the slot reads its own copy.
    """
    lights_sentinel = [{"id": "patched"}]
    nav_sentinel = {"available": "patched"}
    sources_sentinel = [{"id": "patched"}]
    monkeypatch.setattr(backend, "_provider_lights", lambda bridge: lights_sentinel)
    monkeypatch.setattr(backend, "_browse_nav", lambda bridge: nav_sentinel)
    monkeypatch.setattr(backend, "_my_music_sources", lambda bridge: sources_sentinel)

    tidal = StubProvider("tidal", "TIDAL", capabilities={Capability.BROWSE})
    stub = stub_bridge({"tidal": tidal})

    assert WavesBridge.providerLights(stub) is lights_sentinel
    assert WavesBridge.browseNav(stub) is nav_sentinel
    assert WavesBridge.myMusicSources(stub) is sources_sentinel


def test_patched_row_helpers_reach_the_album_row(monkeypatch):
    """A patch on a row helper still drives the row builder that reads it.

    ``_image`` is backend's own helper and ``name_builder_title`` is imported
    from the naming module; both are read as ``backend.<name>`` globals inside
    ``_album_dict``. A move that re-imports either from its definition site
    instead of ``backend`` leaves the suite's patches behind.
    """
    monkeypatch.setattr(backend, "_image", lambda obj, dimension=320: "PATCHED ART")
    monkeypatch.setattr(backend, "name_builder_title", lambda obj: "PATCHED TITLE")

    stub = SimpleNamespace(
        _remember=lambda bucket, key, obj: None,
        providers={"tidal": SimpleNamespace()},
    )
    album = SimpleNamespace(
        id="al1",
        name="Album",
        artist=SimpleNamespace(id="a1", name="Artist", roles=None),
        artists=[SimpleNamespace(id="a1", name="Artist", roles=None)],
        duration=200,
        num_tracks=10,
        popularity=50,
    )

    row = WavesBridge._album_dict(stub, album)

    assert row["art"] == "PATCHED ART"
    assert row["title"] == "PATCHED TITLE"

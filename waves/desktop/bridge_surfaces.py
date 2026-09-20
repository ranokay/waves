"""The provider-surface family: the data every provider surface renders,
composed from the live bridge state and the provider registry.

The surfaces themselves are QML. What they need beyond the fields a provider
descriptor already carries is composed here once, so a third provider's card,
light, chooser tile, shelf group or search group renders with no QML edit.
This module is the source behind the provider cards, the header's status
lights, the Chooser's provider segment, My Music's saved-shelf sources, the
Library section's file rows, Browse's availability, and the search page's
provider-keyed prefs.

The helpers are module-level rather than methods: the schema builder and its
tests carry stub bridges that bind methods selectively, so a helper reads only
the attributes it needs, and several helpers take no bridge at all. backend.py
imports these helpers back by name, which keeps every ``backend._name``
reference and monkeypatch target alive. This module must never import backend.

The vocabulary the surfaces print lives here too (the search section list, the
setup status words, the readable duration spelling). State stays on the bridge:
the provider registry, the probe tables and the tracked sessions are its.
"""

from __future__ import annotations

import logging

from waves.desktop.worker import Worker
from waves.ids import provider_of_id
from waves.library.index import FILES_VIEWS
from waves.providers import Capability, StatusKind

# The subsystem child logger (per the diagnostics conventions): propagates into
# the root "waves" breadcrumb ring while letting verbose logs slice per subsystem.
logger = logging.getLogger("waves.surfaces")


# ----- the shared surface vocabulary ------------------------------------------
# The words and lists the surfaces print, used here and imported back by
# backend's payload builders.


def _fmt_duration(seconds: int | None) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _apple_status(
    enabled: bool,
    *,
    runtime_ready: bool = False,
    signed_in: bool = False,
    needs_attention: bool = False,
    cookies_ready: bool = False,
) -> dict:
    """The Apple status light's ``{"state", "word"}`` (spec §9.2.3).

    One source for both the bridge slot (the page's live mirror) and the
    schema's baked value, so the two can never disagree. The light has five
    states: ``off`` while the component is disabled, ``not_set_up`` once
    enabled but with neither runtime nor sign-in, ``runtime_ready`` when
    the managed N_m3u8DL-RE is provisioned, ``signed_in`` when a verified
    cookies export (cookies tier, no runtime needed) or a wrapper session
    unlocks downloads, and ``needs_attention`` when a saved cookies path
    or runtime needs repair. Precedence is needs_attention > signed_in >
    runtime_ready > not_set_up > off. ``cookies_ready`` without
    ``signed_in`` still lights ``signed_in``: the cookies tier unlocks
    AAC 256 + Atmos with no runtime at all (spec §2).
    """
    # Local import avoids a module-import cycle in tests that stub the bridge.
    from waves.providers.apple.runtime import describe_setup

    described = describe_setup(
        enabled=bool(enabled),
        runtime_ready=bool(runtime_ready),
        signed_in=bool(signed_in),
        needs_attention=bool(needs_attention),
        cookies_ready=bool(cookies_ready),
    )
    return {"state": described["state"], "word": described["word"]}


#: The result sections a search group can carry, in render order. A provider
#: declares the subset its catalog answers (``Provider.search_sections``), and
#: the group only carries those buckets, so the page's type filter can tell
#: "this provider answered nothing" from "this provider never answers these".
_SEARCH_SECTIONS: tuple[str, ...] = ("artists", "albums", "tracks", "videos", "playlists", "mixes")


def _record_in_library(bridge, path: str) -> bool:
    """Is one recorded copy under the library root? A string compare on the
    configured paths (LibraryMixin._path_inside_library), never a stat. A
    module function reached through getattr, so the tests' partial bridges
    that bind ownershipOf alone still answer (False, no library)."""
    inside = getattr(bridge, "_path_inside_library", None)
    if inside is None or not path:
        return False
    try:
        return bool(inside(path))
    except Exception:
        logger.debug("Could not place a recorded copy against the library root", exc_info=True)
        return False


# ----- provider descriptor composition (the cards the page renders) -----
#
# Module-level on purpose: the schema builder and its tests carry stubs that
# bind real methods selectively, so these helpers take the bridge as an
# argument and read only the attributes they need.


def _begin_login(bridge, provider_id: str) -> None:
    """Start a provider's login flow and hand the URL to the GUI.

    One body for the landing panel and the provider card's action, so a
    card's Sign in and the panel's button can never diverge.
    """
    provider = bridge.providers.get(provider_id)
    if provider is None:
        return

    def work() -> None:
        try:
            # The provider owns the flow entry (and rebuilds the session a
            # prior sign-out tore down, so a fresh PKCE login can start).
            url = provider.login_begin()
        except Exception:
            logger.exception("Could not obtain login URL")
            bridge._set_status("Could not start login")
            return
        bridge.loginUrlReady.emit(url)
        bridge._set_status("Finish signing in, then paste the URL back")

    bridge.threadpool.start(Worker(work))


def _provider_sign_out(bridge, provider_id: str) -> None:
    """Sign a provider out by id.

    A provider can register an app-level sign-out flow that owns more than
    the provider's own logout (stopping queued jobs, clearing caches, wiping
    the guest); without one, the provider's neutral ``logout`` runs.
    """
    provider = bridge.providers.get(provider_id)
    if provider is None:
        return
    flows = getattr(bridge, "_provider_signout_flows", {})
    flow = flows.get(provider_id)
    if flow is not None:
        flow()
        return
    try:
        provider.logout()
    except Exception:
        logger.exception("Provider sign-out failed")


def _provider_registry(bridge) -> list:
    """The configured providers, in the registry's insertion order (TIDAL is
    registered first today, so its card leads the section)."""
    providers = getattr(bridge, "providers", None)
    return list(providers.values()) if isinstance(providers, dict) else []


def _source_provider(bridge, source):
    """The provider behind a My Music source id, or None.

    A closed source (a sign-out that raced a load, a registry that moved on)
    answers None and every loader treats it as "nothing to show": never
    another provider's rows.
    """
    providers = getattr(bridge, "providers", None)
    return providers.get(str(source or "")) if isinstance(providers, dict) else None


def _source_rows(provider, row_kind: str, raw: list) -> list:
    """One engine item per row, through the source's OWN row vocabulary.

    The pane renders whatever its provider's ``row_for`` answers; an item a
    provider cannot render (an empty row) is dropped rather than shown as a
    blank. This is the one place the pane's rows are built, so a second
    provider's shelves never take TIDAL's path.
    """
    rows = []
    for item in raw:
        row = provider.row_for(row_kind, item)
        if row:
            rows.append(row)
    return rows


def _lib_key(source, category) -> tuple[str, str]:
    """One My Music shelf page's cache key: a source's category is its own
    page, sort, revalidation stamp and in-flight slot."""
    return (str(source or ""), str(category or ""))


def _lib_disk_key(source, category) -> str:
    """The page cache's flat spelling of a shelf page.

    Provider ids are registry keys and never carry a colon, so the pair is
    unambiguous ("tidal:albums"); the version bump is what retires the older
    bare-category keys.
    """
    return f"{source}:{category}"


def _session_logged_in(bridge, provider) -> bool:
    """Whether a session-kind provider's card reads signed in.

    A provider whose session the bridge tracks answers from the bridge's own
    flag: the login flow, the header and every catalog read move it together,
    and the provider's live check can trail a fresh sign-in. A provider the
    bridge does not track answers for itself.
    """
    if getattr(provider, "id", "") in getattr(bridge, "_tracked_sessions", ()):
        return bool(getattr(bridge, "_logged_in", False))
    try:
        return bool(provider.is_logged_in)
    except Exception:
        logger.debug("Provider session read failed", exc_info=True)
        return False


def _provider_session_field(descriptor, logged_in: bool) -> dict:
    """The status row a session-kind provider card carries.

    One shape for every provider: the row reports the session and offers the
    matching action, so a second session-kind provider renders its card
    without a QML or schema branch. It stages no edit.
    """
    return {
        "key": f"provider_{descriptor.id}_session",
        "provider": descriptor.id,
        "label": "Session",
        "help": (
            f"The {descriptor.name} account Waves is working from. This row "
            "reports the session and offers the matching action: "
            "sign in while signed out, sign out while signed in."
        ),
        "type": "status",
        "value": "signed_in" if logged_in else "not_signed_in",
        "word": "Signed in" if logged_in else "Not signed in",
        "actions": [
            {
                "label": "Sign out" if logged_in else "Sign in",
                "action": f"{descriptor.id}_{'signout' if logged_in else 'signin'}",
            }
        ],
    }


def _provider_card(provider) -> dict:
    """One Providers card, composed from the provider's descriptor.

    The card's identity, blurb and field list are the provider's; the live
    data behind those keys stays the bridge's (built where the probes live).
    A session-kind provider's generated status row leads the card even when
    its descriptor does not list the key, so a provider that contributes
    nothing but identity still renders.
    """
    descriptor = provider.descriptor()
    fields = list(descriptor.settings_fields)
    if descriptor.status_kind == StatusKind.SESSION:
        session_key = f"provider_{descriptor.id}_session"
        if session_key not in fields:
            fields.insert(0, session_key)
    return {
        "name": descriptor.name,
        "id": f"providers_{descriptor.id}",
        "desc": descriptor.card_desc,
        "logo": descriptor.logo,
        "logo_width": descriptor.logo_width,
        "logo_header_width": descriptor.logo_header_width,
        "logo_header_height": descriptor.logo_header_height,
        "fields": fields,
    }


# ----- My Music's saved-shelf sources -----
#
# Which providers contribute saved shelves to the My Music pane, what each
# source's group is labelled, and which shelf categories each can fill.
# Module-level and answer-only on purpose: a provider that contributes
# shelves does so from its capability and its live session, so a third
# provider needs no QML branch, and these lists are what a stub bridge can
# drive in tests without a Qt session.

# The pane's neutral shelf vocabulary, in strip order: (id, label, the
# capability a source must declare to fill it). The ids are the loaders'
# category names and what the pane's panes switch on; the labels are the
# strip's words; the ids never name a provider. "home" is a source's own
# landing (its recent favourites); the rest are its shelves.
_SHELF_CATEGORIES: tuple[tuple[str, str, Capability], ...] = (
    ("home", "Home", Capability.FAVORITES),
    ("albums", "Albums", Capability.FAVORITES),
    ("tracks", "Tracks", Capability.FAVORITES),
    ("artists", "Artists", Capability.FAVORITES),
    ("playlists", "Playlists", Capability.PLAYLISTS),
    ("mixes", "Mixes", Capability.MIXES),
    ("videos", "Videos", Capability.VIDEOS),
)

# The favourites-backed categories: (category id, the favourites kind the
# provider pages, the row_for kind its row vocabulary names). Everything the
# pane loads through a source goes provider -> favourites_page -> row_for; a
# provider that declares FAVORITES and answers those two calls contributes
# real shelves with no bridge or QML branch.
_FAVOURITES_CATEGORIES: dict[str, tuple[str, str]] = {
    "albums": ("albums", "album"),
    "tracks": ("tracks", "track"),
    "artists": ("artists", "artist"),
    "videos": ("videos", "video"),
}


def _source_categories(provider) -> list[dict]:
    """The shelf categories one source's provider can fill, in strip order.

    Capability-driven (ADR 0008): a provider that cannot fill a shelf
    contributes no tab for it rather than an empty one, and a provider that
    later declares one of these capabilities grows its strip with no QML
    edit. The provider may be None (a registry entry with no live provider);
    it then contributes nothing.
    """
    capabilities = getattr(provider, "capabilities", None) or frozenset()
    return [
        {"id": category_id, "label": label}
        for category_id, label, capability in _SHELF_CATEGORIES
        if capability in capabilities
    ]


def _human_join(words: list[str]) -> str:
    """A list in the app's sentence prose: "a, b and c" (no Oxford comma)."""
    parts = [str(w) for w in words if str(w)]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" and {parts[-1]}"


def _provider_can_fill_shelves(bridge, provider) -> bool:
    """Whether a provider has a live account session to fill saved shelves.

    Shelf sources are account libraries: a provider that declares
    Capability.FAVORITES but is signed out cannot fill them, so it is not a
    source (its pane shows its own empty state). The session truth is the
    bridge's own (a tracked session reads the bridge's flag, see
    ``_session_logged_in``); the descriptor's status kind says whether the
    provider has a session to read at all.
    """
    if provider.descriptor().status_kind != StatusKind.SESSION:
        return False
    return _session_logged_in(bridge, provider)


def _saved_shelf_sources(bridge) -> list[dict]:
    """One descriptor per provider whose saved shelves My Music can render.

    A provider contributes when it declares Capability.FAVORITES and its
    account session is live. ``label`` is source-qualified only when more
    than one provider contributes: with a single source the pane's rows ARE
    that source, so a label would only repeat it, and the pane renders
    exactly that. A third provider contributes a
    descriptor here without a QML edit.
    """
    descriptors = [
        provider.descriptor()
        for provider in _provider_registry(bridge)
        if Capability.FAVORITES in getattr(provider, "capabilities", frozenset())
        and _provider_can_fill_shelves(bridge, provider)
    ]
    qualified = len(descriptors) > 1
    return [
        {
            "id": descriptor.id,
            "name": descriptor.name,
            "label": f"Saved from {descriptor.name}" if qualified else "",
        }
        for descriptor in descriptors
    ]


def _my_music_sources(bridge) -> list[dict]:
    """The pane's source groups: one descriptor per source, in registry
    order, each carrying the shelf categories it can fill.

    The pane renders exactly this list -- a strip from ``categories``, a
    group label from ``label`` -- and every page it loads goes back through
    the source's own provider, so a provider that later declares FAVORITES
    (or PLAYLISTS/MIXES/VIDEOS) appears with no QML edit.
    """
    providers = getattr(bridge, "providers", {})
    providers = providers if isinstance(providers, dict) else {}
    return [
        {**source, "categories": _source_categories(providers.get(source["id"]))}
        for source in _saved_shelf_sources(bridge)
    ]


def _my_music_empty(bridge) -> dict:
    """The pane's one empty state while no source can fill a shelf.

    A session provider that declares FAVORITES but has no live session is
    the provider that could fill the pane, so the state names it and offers
    its own sign-in verb; the sentences are composed from that provider's
    descriptor and category list, so a second provider gets its own words
    with no QML copy. Returns ``{}`` when no provider could fill shelves at
    all (a signed-out Apple-only install has nothing to sign in to).
    """
    for provider in _provider_registry(bridge):
        if Capability.FAVORITES not in getattr(provider, "capabilities", frozenset()):
            continue
        if _provider_can_fill_shelves(bridge, provider):
            continue
        descriptor = provider.descriptor()
        if descriptor.status_kind != StatusKind.SESSION:
            # A provider that never holds a session can never fill a shelf
            # (see _provider_can_fill_shelves), so nothing here is missing its
            # action: the pane stays quiet rather than offering a setup that
            # would not produce shelves.
            continue
        shelves = [c["label"].lower() for c in _source_categories(provider) if c["id"] != "home"]
        return {
            "provider": descriptor.id,
            "action": "signin",
            "message": f"My Music is your {descriptor.name} library",
            "detail": f"Sign in to see your {_human_join(shelves)}.",
            "action_label": f"Sign in to {descriptor.name}",
        }
    return {}


# ----- the Library section's file rows (ADR 0007) -----
# The pane's Library section is provider-independent: its rows come from the
# scan's own file pages, never a provider fetch. These rows carry the two
# things the scan cannot: the provider the file came from, named by the item
# id's own namespace, and the readable duration the UI prints.


def _library_file_row(row: dict, logos: dict[str, str] | None = None) -> dict:
    """One local library file as a My Music row (ADR 0007).

    The provider is derived from the file's item id -- the namespace the
    download gate wrote, a bare id reading as TIDAL's (``namespaced_id``'s own
    rule), never guessed from the folder or the row -- so a legacy file
    badges like a new one and an untagged file carries no provider at all.
    ``logos`` maps a provider id to its descriptor's mark; the row carries it
    so the badge renders the provider that actually owns the namespace, even
    a provider whose id QML has never seen.
    """
    item_id = str(row.get("item_id") or "")
    length = int(row.get("length", 0) or 0)
    provider = provider_of_id(item_id)
    return {
        "id": item_id,
        "item_id": item_id,
        "provider": provider,
        "provider_logo": str((logos or {}).get(provider, "")),
        "title": str(row.get("title") or ""),
        "artist": str(row.get("artist") or row.get("album_artist") or ""),
        "album": str(row.get("album") or ""),
        "album_artist": str(row.get("album_artist") or ""),
        "year": str(row.get("year") or ""),
        "folder": str(row.get("folder_path") or ""),
        "duration": _fmt_duration(length),
        "duration_sec": length,
        "codec": str(row.get("codec") or ""),
        "audio_type": str(row.get("audio_type") or ""),
    }


def _provider_descriptor_dict(descriptor) -> dict:
    """The badge/head fields of a provider descriptor.

    One shape for the surfaces that ask the bridge: a badge renders the logo,
    a section head the name and the header tile's mark sizes, and the tests
    read all of it. The library's bulk rows carry the same fields instead (see
    ``_library_file_row``), so a badge there costs no per-row crossing. Nothing
    here names a provider.
    """
    return {
        # getattr, not attribute access: a third provider's descriptor may
        # carry only the fields its own surfaces need, and a badge must still
        # render its mark.
        "id": str(getattr(descriptor, "id", "") or ""),
        "name": str(getattr(descriptor, "name", "") or ""),
        "logo": str(getattr(descriptor, "logo", "") or ""),
        # The dataclass's own defaults, not zero: a partial descriptor still
        # renders a mark, never a zero-size one.
        "logo_header_width": int(getattr(descriptor, "logo_header_width", 14) or 14),
        "logo_header_height": int(getattr(descriptor, "logo_header_height", 14) or 14),
        # The search group head's furniture: a descriptor that
        # names no style renders the neutral one.
        "head_style": str(getattr(descriptor, "head_style", "") or "plain"),
    }


def _provider_logos(bridge) -> dict[str, str]:
    """Every registered provider's mark by id, from its own descriptor.

    Built once per page so a badge shows the namespace's provider mark, and a
    namespace no provider claims maps to nothing (never another provider's
    logo: an unknown file must not wear TIDAL's mark). A provider whose
    descriptor cannot be read contributes no mark instead of failing the
    page: the rows are the scan's answer, the marks are decoration.
    """
    logos: dict[str, str] = {}
    for provider in _provider_registry(bridge):
        try:
            descriptor = provider.descriptor()
            logos[str(descriptor.id)] = str(descriptor.logo or "")
        except Exception:
            logger.debug("Could not read a provider's mark for a library row", exc_info=True)
    return logos


#: The Library section's view labels, keyed by the scan's own view ids
#: (library_index.FILES_VIEWS, Saved first). Words, not behaviour: QML renders
#: these, so a copy change needs no QML edit. A view with no entry renders its
#: own id rather than failing the section (see myMusicLibrary).
_LIBRARY_VIEW_LABELS = {"saved": "Saved", "all": "All files"}


def _library_files_view(view) -> str:
    """One of the Library section's two view ids (``library_index.FILES_VIEWS``),
    defaulting to the first (Saved, the section's own default).

    QML reads the ids from ``myMusicLibrary()``, so an unknown value is a
    wiring bug rather than a third view: it is answered with the default view
    instead of an empty list the user cannot explain. The scan's own reader
    stays strict -- this is the one boundary a typo can arrive through.
    """
    text = str(view or "")
    return text if text in FILES_VIEWS else FILES_VIEWS[0]


# ----- the header's per-provider lights -----
#
# The top bar's compact status marks, one per provider that has a status to
# report. Composed here from the provider's descriptor and the live state its
# ``status_kind`` names, so a third provider appears in the header with no QML
# edit and no surface says "OFFLINE" about an account the app can still work
# without. A provider with no status (StatusKind.NONE) contributes no light,
# and neither does a SETUP provider that is off: a disabled provider is not
# availability to report. TIDAL sign-out lives on its provider card, never
# here (the card already renders the state-matched action).


def _provider_setup_flags(bridge, provider) -> dict:
    """The live flags behind a SETUP provider's light.

    The probe lives where the provider is wired (the bridge owns the runtime
    and cookies reads); a provider whose probe is missing or fails reads as
    disabled, so it contributes no light rather than a false one.
    """
    probe = getattr(bridge, "_provider_status_probes", {}).get(getattr(provider, "id", ""))
    if probe is None:
        return {}
    try:
        return dict(probe() or {})
    except Exception:
        logger.debug("A provider's setup-status probe failed", exc_info=True)
        return {}


def _provider_light(bridge, provider) -> dict | None:
    """One provider's header light, or None when it has no status to report.

    The word is the user-facing truth for the mark; nothing here is provider
    identity logic, only the shape the descriptor's status_kind names. A
    SETUP provider's light is the shared setup-light vocabulary (spec
    §9.2.3): its live flags come from the probe registered where the
    provider is wired, and a provider that needs different words grows the
    descriptor contract, not a branch here.
    """
    descriptor = provider.descriptor()
    if descriptor.status_kind == StatusKind.SESSION:
        logged_in = _session_logged_in(bridge, provider)
        return {
            "id": descriptor.id,
            "name": descriptor.name,
            "state": "signed_in" if logged_in else "signed_out",
            # The same words as the provider card's session row, so the
            # header and Settings never disagree about one account state.
            "word": "Signed in" if logged_in else "Signed out",
        }
    if descriptor.status_kind == StatusKind.SETUP:
        flags = _provider_setup_flags(bridge, provider)
        described = _apple_status(
            bool(flags.get("enabled", False)),
            runtime_ready=bool(flags.get("runtime_ready", False)),
            signed_in=bool(flags.get("signed_in", False)),
            needs_attention=bool(flags.get("needs_attention", False)),
            cookies_ready=bool(flags.get("cookies_ready", False)),
        )
        if described["state"] == "off":
            return None
        return {
            "id": descriptor.id,
            "name": descriptor.name,
            "state": described["state"],
            "word": described["word"],
        }
    return None


def _provider_lights(bridge) -> list[dict]:
    """Every provider light, in the registry's insertion order."""
    lights = (_provider_light(bridge, provider) for provider in _provider_registry(bridge))
    return [light for light in lights if light is not None]


# ----- the Chooser's control and provider segment -----
#
# The per-click Chooser belongs to the control and the provider metadata, not
# to Apple: a TIDAL-only install gets it, a provider that declares no per-click
# options gets no chevron, and a third provider's segment tile renders from its
# descriptor with no QML branch.

# The download kinds that carry the per-click control (spec §7.2): track rows
# and collection pages. Bulk sweeps keep Settings and a single face.
# ``downloadWithChooser``'s dispatch templates must cover every kind that
# appears here (a kind it does not know falls back to the plain download slot
# there).
_CHOOSER_KINDS: tuple[str, ...] = ("track", "album", "playlist", "mix", "video")


def _provider_is_enabled(bridge, provider) -> bool:
    """Whether a provider is enabled, from the same flags its light reads.

    A SESSION provider (TIDAL) has no switch and is always on; a SETUP
    provider answers from its live setup flags, a missing probe reading off --
    the same rule its status light follows. No provider id enters the rule.
    """
    try:
        descriptor = provider.descriptor()
    except Exception:
        logger.debug("A provider's descriptor failed; treating it as disabled", exc_info=True)
        return False
    if descriptor.status_kind is not StatusKind.SETUP:
        return True
    return bool(_provider_setup_flags(bridge, provider).get("enabled", False))


def _chooser_provider_tiles(bridge, selected_id: str) -> list[dict]:
    """The Chooser's provider segment tiles, descriptor-driven.

    One tile per ENABLED provider; the selected provider always gets its tile
    even while its switch is off (the row is on screen already, and hiding the
    selected tile would leave a bare segment). Each carries the descriptor's
    own name and mark, so QML renders a third provider's tile with no branch
    and no provider id or asset path in QML.
    """
    tiles: list[dict] = []
    for provider in _provider_registry(bridge):
        try:
            descriptor = provider.descriptor()
        except Exception:
            logger.debug("A provider's descriptor failed; no Chooser tile for it", exc_info=True)
            continue
        pid = str(getattr(descriptor, "id", "") or "")
        if not pid:
            continue
        if pid != selected_id and not _provider_is_enabled(bridge, provider):
            continue
        tiles.append(
            {
                "id": pid,
                "name": str(getattr(descriptor, "name", "") or pid),
                "logo": str(getattr(descriptor, "logo", "") or ""),
                "logo_width": int(getattr(descriptor, "logo_width", 0) or 0),
                "selected": pid == selected_id,
            }
        )
    return tiles


def _browse_nav(bridge) -> dict:
    """Browse's availability for the header and its landing pane.

    Browse is editorial and account-scoped: the destination exists while a
    configured provider declares ``Capability.BROWSE`` and is absent when none
    does (the capability is the whole rule; provider identity never enters
    it). The pane is filled by the first browse-capable provider in the
    registry's order, so ``signed_in`` reports that source's live session:
    false, and the landing pane offers its sign-in call to action -- never a
    blank page.
    """
    source = next(
        (
            provider
            for provider in _provider_registry(bridge)
            if Capability.BROWSE in getattr(provider, "capabilities", frozenset())
        ),
        None,
    )
    return {
        "available": source is not None,
        "signed_in": bool(source is not None and _session_logged_in(bridge, source)),
    }


# The status line for an Apple verb with no implementation yet. Present tense on
# purpose: a future-tense promise would claim a ship date the build cannot back,
# and one constant keeps the artist, mix and video refusals from drifting apart.
_APPLE_UNAVAILABLE_STATUS = "Not available for Apple Music yet"


def _is_provider_surface_pref(key: str) -> bool:
    """Whether a waves.json key is one of the search page's provider-keyed
    housekeeping prefs: a provider group's fold
    (``search_provider_<id>_collapsed``) or a section's SHOW ALL state
    (``<id>_search_sec_<section>_expanded``).

    Validated by shape rather than enumerated, because a provider the app has
    never heard of must still save and restore its own state with no wiring;
    every accepted key holds a bool, so ``setWavesPref`` materializes it as
    one.
    """
    if key.startswith("search_provider_") and key.endswith("_collapsed"):
        return len(key) > len("search_provider__collapsed")
    for section in _SEARCH_SECTIONS:
        suffix = f"_search_sec_{section}_expanded"
        if key.endswith(suffix) and len(key) > len(suffix):
            return True
    return False

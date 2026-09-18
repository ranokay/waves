"""The Chooser's answers come from provider metadata, not provider identity.

Each Provider declares its quality rungs, the Settings field holding its
default tier, the audio types it serves and the settings card its per-provider
mirrors live under. The bridge renders the Chooser from those declarations, so
a third provider registered with the right capabilities and metadata gets the
same options and gates without a bridge branch. A provider that declares
nothing answers neutrally: no rungs, no default, no audio types, no card.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from support.provider_fakes import BareProvider

from waves.constants import CTX_APPLE, CTX_TIDAL, QualityTier
from waves.providers import AudioType, Capability, QualityOption, StatusKind
from waves.providers.apple import AppleProvider
from waves.providers.tidal import TidalProvider
from waves.waves_ui.backend import WavesBridge

# The fields the bridge's chooser reads off a Provider. A stub stands in for
# an instance wherever the provider's own methods are not under test.
_METADATA_FIELDS = ("name", "capabilities", "quality_options", "quality_setting", "audio_types", "settings_card")


def _metadata(cls, **over):
    fields = {name: getattr(cls, name) for name in _METADATA_FIELDS}
    fields.update(over)
    return SimpleNamespace(**fields)


class _InlinePool:
    @staticmethod
    def start(worker, priority: int = 0):
        worker.fn()


class _Signal:
    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args[0] if len(args) == 1 else args)


def _bridge(providers=None, **settings_over):
    b = SimpleNamespace()
    settings = {
        "tidal_quality_audio": "HIGH",
        "apple_quality_audio": "LOSSLESS",
        "default_audio_type": "stereo",
        "apple_enabled": False,
    }
    settings.update(settings_over)
    b.settings = SimpleNamespace(data=SimpleNamespace(**settings))
    b.providers = (
        providers
        if providers is not None
        else {CTX_TIDAL: TidalProvider(SimpleNamespace()), CTX_APPLE: AppleProvider()}
    )
    b._objs = {"track": {}}
    b.qualityOverridesChanged = _Signal()
    b.qualityChoiceChanged = _Signal()
    b.ownershipChanged = _Signal()
    b.appleStatusChanged = _Signal()
    b.targetTierChanged = _Signal()
    b.staged: dict = {}
    b.applySettings = lambda values: b.staged.update(values)
    for name in (
        "_provider_meta",
        "_chooser_provider_of",
        "_chooser_tier_entries",
        "chooserTiers",
        "chooserDefaultTier",
        "_chooser_default_tier_word",
        "_chooser_default_audio",
        "_chooser_atmos_only",
        "_chooser_supports",
        "chooserSupported",
        "_artist_download_supports",
        "artistDownloadSupported",
        "providerDescriptor",
        "chooserDefaults",
        "saveChooserDefaults",
        "_chooser_ask_for",
        "_chooser_normalize_audio",
        "_psetting",
        "_get_apple_enabled",
    ):
        setattr(b, name, getattr(WavesBridge, name).__get__(b, SimpleNamespace))
    return b


_QOBUZ = SimpleNamespace(
    name="Qobuz",
    capabilities=frozenset({Capability.SEARCH, Capability.LYRICS, Capability.ART}),
    quality_options=(
        QualityOption(QualityTier.HI_RES_LOSSLESS, "FLAC 24-bit"),
        QualityOption(QualityTier.LOSSLESS, "FLAC 16-bit"),
        QualityOption(QualityTier.HIGH, "MP3 320"),
    ),
    quality_setting="qobuz_quality_audio",
    audio_types=frozenset({AudioType.STEREO}),
    settings_card="qobuz",
)


def _qobuz_descriptor():
    """A third provider's descriptor, the identity its segment tile reads."""
    return SimpleNamespace(
        id="qobuz",
        name="Qobuz",
        logo="assets/providers/qobuz.png",
        logo_width=22,
        status_kind=StatusKind.NONE,
    )


_QOBUZ.descriptor = _qobuz_descriptor


# --------------------------------------------------------------------------- #
# The declared metadata
# --------------------------------------------------------------------------- #
def test_the_base_metadata_defaults_are_neutral():
    bare = BareProvider()
    assert bare.quality_options == ()
    assert bare.quality_setting == ""
    assert bare.audio_types == frozenset()
    assert bare.settings_card == ""


def test_tidal_declares_its_full_chooser_metadata():
    provider = TidalProvider(SimpleNamespace())
    assert [(o.tier, o.detail) for o in provider.quality_options] == [
        (QualityTier.HI_RES_LOSSLESS, "FLAC 24-bit up to 192 kHz"),
        (QualityTier.LOSSLESS, "FLAC 16-bit/44.1 kHz"),
        (QualityTier.HIGH, "AAC 320"),
        (QualityTier.LOW, "AAC 96"),
    ]
    assert provider.quality_setting == "tidal_quality_audio"
    assert provider.audio_types == frozenset({AudioType.STEREO, AudioType.ATMOS})
    assert provider.settings_card == "tidal"


def test_apple_declares_its_three_rung_chooser_metadata():
    provider = AppleProvider()
    assert [(o.tier, o.detail) for o in provider.quality_options] == [
        (QualityTier.HI_RES_LOSSLESS, "ALAC 24/192"),
        (QualityTier.LOSSLESS, "ALAC 16/44.1"),
        (QualityTier.HIGH, "AAC 256"),
    ]
    assert provider.quality_setting == "apple_quality_audio"
    assert provider.audio_types == frozenset({AudioType.STEREO, AudioType.ATMOS})
    assert provider.settings_card == "apple"


# --------------------------------------------------------------------------- #
# The chooser answers both shipped providers as before
# --------------------------------------------------------------------------- #
def test_chooser_tiers_render_each_providers_declared_rungs():
    b = _bridge()
    assert [(e["value"], e["word"], e["detail"]) for e in b.chooserTiers("tidal")] == [
        ("HI_RES_LOSSLESS", "HI-RES", "FLAC 24-bit up to 192 kHz"),
        ("LOSSLESS", "LOSSLESS", "FLAC 16-bit/44.1 kHz"),
        ("HIGH", "HIGH", "AAC 320"),
        ("LOW", "LOW", "AAC 96"),
    ]
    assert [(e["value"], e["word"], e["detail"]) for e in b.chooserTiers("apple")] == [
        ("HI_RES_LOSSLESS", "HI-RES", "ALAC 24/192"),
        ("LOSSLESS", "LOSSLESS", "ALAC 16/44.1"),
        ("HIGH", "HIGH", "AAC 256"),
    ]


def test_chooser_default_tier_reads_each_providers_own_setting():
    b = _bridge(tidal_quality_audio="HI_RES_LOSSLESS", apple_quality_audio="HIGH")
    assert b.chooserDefaultTier("tidal") == "HI-RES"
    assert b.chooserDefaultTier("apple") == "HIGH"


def test_chooser_defaults_carry_provider_audio_options_and_toggles():
    b = _bridge()
    d = b.chooserDefaults("apple:1", "track")
    assert d["provider"] == "apple"
    assert d["audioOptions"] == ["stereo", "atmos", "both"]
    assert d["tier"] == "LOSSLESS"
    assert d["lyricsEmbed"] is False and d["coverEmbed"] is True


def test_chooser_pins_only_listed_tiers_for_each_provider():
    b = _bridge()
    assert b._chooser_ask_for("tidal", "LOW") == ("LOW", "LOW")
    assert b._chooser_ask_for("apple", "LOW") is None
    assert b._chooser_ask_for("apple", "HIGH") == ("HIGH", "HIGH")


def test_apple_tracks_never_collapse_to_atmos_only():
    """An Apple track always advertises stereo, so the collapse never fires."""
    b = _bridge()
    b._objs["track"]["apple:1"] = {"id": "1", "attributes": {"audioTraits": ["dolby-atmos"]}}
    assert b.chooserDefaults("apple:1", "track")["atmosOnly"] is False


def test_set_as_defaults_writes_each_providers_card_and_offered_tier():
    b = _bridge()
    b.saveChooserDefaults({"provider": "apple", "tier": "HIGH", "audioType": "both", "lyricsEmbed": True})
    assert b.staged == {"apple_quality_audio": "HIGH", "default_audio_type": "both", "apple_lyrics_embed": True}
    b.staged.clear()
    # Apple has no LOW rung: the refused word stages nothing for quality.
    b.saveChooserDefaults({"provider": "apple", "tier": "LOW", "audioType": ""})
    assert "apple_quality_audio" not in b.staged
    b.staged.clear()
    b.saveChooserDefaults({"provider": "tidal", "tier": "LOW", "audioType": "", "coverFile": False})
    assert b.staged == {"tidal_quality_audio": "LOW", "tidal_cover_album_file": False}


# --------------------------------------------------------------------------- #
# A third provider needs no branch edits for the covered questions
# --------------------------------------------------------------------------- #
def test_a_third_provider_gets_chooser_options_and_gates_from_its_metadata():
    b = _bridge(providers={CTX_TIDAL: _metadata(TidalProvider), "qobuz": _QOBUZ}, qobuz_quality_audio="LOSSLESS")

    assert [e["word"] for e in b.chooserTiers("qobuz")] == ["HI-RES", "LOSSLESS", "HIGH"]
    assert b.chooserDefaultTier("qobuz") == "LOSSLESS"

    d = b.chooserDefaults("qobuz:1", "track")
    assert d["provider"] == "qobuz"
    assert d["tier"] == "LOSSLESS"
    assert d["audioOptions"] == ["stereo"], "a stereo-only provider offers no Atmos words"
    assert d["atmosOnly"] is False

    assert b._chooser_ask_for("qobuz", "HI-RES") == ("HI_RES_LOSSLESS", "HI-RES")
    assert b._chooser_ask_for("qobuz", "LOW") is None, "a rung the provider does not list is not pinned"
    assert b._chooser_normalize_audio("atmos", "qobuz") is None
    assert b._chooser_normalize_audio("stereo", "qobuz") == "stereo"

    b.saveChooserDefaults({"provider": "qobuz", "tier": "HI-RES", "lyricsEmbed": True})
    assert b.staged == {"qobuz_quality_audio": "HI_RES_LOSSLESS", "qobuz_lyrics_embed": True}


def test_a_third_provider_without_the_capability_gets_no_toggle_gate():
    provider = SimpleNamespace(
        name="Mute",
        capabilities=frozenset(),
        quality_options=(QualityOption(QualityTier.HIGH, "AAC"),),
        quality_setting="mute_quality_audio",
        audio_types=frozenset({AudioType.STEREO}),
        settings_card="mute",
    )
    b = _bridge(providers={"mute": provider}, mute_lyrics_embed=True, mute_cover_album_file=True)
    d = b.chooserDefaults("mute:1", "track")
    assert d["lyricsEmbed"] is False and d["lyricsFile"] is False and d["lyricsTtml"] is False
    assert d["coverEmbed"] is False and d["coverFile"] is False


def test_chooser_supported_is_capability_driven_not_provider_identity():
    """The split button belongs to the control, not to Apple (issue #235 /
    TS-05): a TIDAL-only install gets it, an unsupported kind does not, and a
    provider whose metadata offers nothing per-click answers False instead of
    drawing a control that opens empty."""
    b = _bridge(apple_enabled=False)
    assert b.chooserSupported("t1", "track") is True
    assert b.chooserSupported("t1", "album") is True
    assert b.chooserSupported("apple:1", "track") is True, "the Apple switch is not the gate"
    assert b.chooserSupported("t1", "artist") is False
    assert b.chooserSupported("t1", "folder") is False
    assert b.chooserSupported("", "track") is False

    bare = SimpleNamespace(
        name="Mute",
        capabilities=frozenset(),
        quality_options=(),
        quality_setting="",
        audio_types=frozenset(),
        settings_card="mute",
    )
    b = _bridge(providers={"mute": bare})
    assert b.chooserSupported("mute:1", "track") is False


def test_the_artist_download_verdict_is_capability_driven_not_provider_identity():
    """Issue #288: the artist page's discography control renders from a
    provider capability, so no QML branch names a provider. Apple's catalog
    answers no artist sweep; TIDAL's does; a third provider declaring the
    capability gets the control and one without it never does."""
    b = _bridge()

    assert b.artistDownloadSupported("") is False, "no artist, no control"
    assert b.artistDownloadSupported(f"{CTX_APPLE}:artist-1") is False
    assert b.artistDownloadSupported("artist-1") is True

    qobuz = _metadata(_QOBUZ, capabilities=frozenset({Capability.ARTIST_DOWNLOAD}))
    third = _bridge(providers={CTX_TIDAL: _metadata(TidalProvider), "qobuz": qobuz})
    assert third.artistDownloadSupported("qobuz:artist-1") is True

    bare = _bridge(providers={CTX_TIDAL: _metadata(TidalProvider), "bare": _metadata(BareProvider)})
    assert bare.artistDownloadSupported("bare:artist-1") is False


class _RaisingCapabilities:
    """A malformed registration whose capability answer blows up."""

    @property
    def capabilities(self):
        raise RuntimeError("no capability answer")


def test_a_failing_capability_probe_hides_the_control():
    """A probe that raises must hide the control, never fail open to a live
    button (the same contract chooserSupported's guard keeps, issue #288)."""
    b = _bridge(providers={CTX_TIDAL: _metadata(TidalProvider), "apple": _RaisingCapabilities()})

    assert b.artistDownloadSupported("apple:artist-1") is False


def test_provider_descriptor_answers_by_namespace_or_provider_id():
    """Issue #278: every badge and group head renders the descriptor this
    answers, so QML never parses an id prefix nor carries a provider asset
    path. A bare legacy id reads as TIDAL's, a provider id matches exactly
    (a head asking for its own provider), an id no registered provider claims
    answers None (never another provider's mark), and a descriptor that
    cannot be read contributes nothing."""
    b = _bridge()

    apple = b.providerDescriptor("apple:artist-1")
    assert apple is not None and apple["id"] == "apple" and apple["logo"].endswith("apple-music.png")
    assert b.providerDescriptor("artist-1")["id"] == "tidal"
    assert b.providerDescriptor("apple")["id"] == "apple"
    assert b.providerDescriptor("tidal")["id"] == "tidal"
    assert b.providerDescriptor("unclaimed:artist-1") is None
    assert b.providerDescriptor("") is None

    qobuz = _metadata(_QOBUZ, descriptor=_qobuz_descriptor)
    third = _bridge(providers={CTX_TIDAL: _metadata(TidalProvider), "qobuz": qobuz})
    assert third.providerDescriptor("qobuz:album-1")["logo"].endswith("qobuz.png")

    def _broken():
        raise RuntimeError("no descriptor")

    broken = _bridge(
        providers={CTX_TIDAL: _metadata(TidalProvider), "broken": _metadata(BareProvider, descriptor=_broken)}
    )
    assert broken.providerDescriptor("broken:artist-1") is None

    none_descriptor = _bridge(
        providers={CTX_TIDAL: _metadata(TidalProvider), "none": _metadata(BareProvider, descriptor=lambda: None)}
    )
    assert none_descriptor.providerDescriptor("none:artist-1") is None


def test_chooser_segment_tiles_come_from_the_enabled_providers_descriptors():
    """The provider segment is bridge data (issue #235): a disabled provider
    draws no tile, the row's own provider always does, and each tile carries
    the descriptor's own name and mark -- no provider name or asset path in
    QML, so a third provider renders with no QML edit."""
    b = _bridge(apple_enabled=False)
    d = b.chooserDefaults("t1", "track")
    assert [t["id"] for t in d["providers"]] == ["tidal"]
    assert d["providers"][0]["selected"] is True

    # A third provider with no setup switch is always on; it renders from its
    # descriptor and metadata alone.
    b = _bridge(
        providers={CTX_TIDAL: TidalProvider(SimpleNamespace()), "qobuz": _QOBUZ}, qobuz_quality_audio="LOSSLESS"
    )
    tiles = b.chooserDefaults("qobuz:1", "track")["providers"]
    assert [t["id"] for t in tiles] == ["tidal", "qobuz"]
    assert [t["selected"] for t in tiles] == [False, True]
    qobuz = tiles[1]
    assert qobuz["name"] == "Qobuz" and qobuz["logo"] == "assets/providers/qobuz.png"

    b = _bridge(apple_enabled=True)
    b._provider_status_probes = {CTX_APPLE: lambda: {"enabled": True}}
    tiles = b.chooserDefaults("apple:1", "track")["providers"]
    assert [t["id"] for t in tiles] == ["tidal", "apple"]
    assert [t["selected"] for t in tiles] == [False, True]
    apple = tiles[1]
    descriptor = AppleProvider.descriptor()
    assert apple["name"] == descriptor.name
    assert apple["logo"] == descriptor.logo
    assert apple["logo_width"] == descriptor.logo_width


def test_the_chooser_carries_which_sections_apply_per_provider():
    """Each popover section is gated on provider metadata, not identity: the
    lyrics/art sections follow the capabilities and the TTML toggle follows
    the provider's own engine fact (issue #235)."""
    b = _bridge()
    tidal = b.chooserDefaults("t1", "track")
    apple = b.chooserDefaults("apple:1", "track")
    assert tidal["showLyrics"] is True and tidal["showArt"] is True
    assert tidal["showLyricsTtml"] is False, "TIDAL writes no verbatim TTML sidecar"
    assert apple["showLyrics"] is True and apple["showArt"] is True
    assert apple["showLyricsTtml"] is True

    bare = SimpleNamespace(
        name="Mute",
        capabilities=frozenset(),
        quality_options=(),
        quality_setting="",
        audio_types=frozenset(),
        settings_card="mute",
    )
    d = _bridge(providers={"mute": bare}).chooserDefaults("mute:1", "track")
    assert d["showLyrics"] is False and d["showArt"] is False and d["showLyricsTtml"] is False


def test_a_stereo_only_provider_clamps_the_stored_both_default():
    """A 'both' Settings default cannot survive for a provider with no Atmos
    words: the popover would open with no tile selected and send a word the
    provider cannot fetch (issue #235)."""
    stereo_only = SimpleNamespace(
        name="Qobuz",
        capabilities=frozenset({Capability.LYRICS}),
        quality_options=(QualityOption(QualityTier.LOSSLESS, "FLAC 16-bit"),),
        quality_setting="qobuz_quality_audio",
        audio_types=frozenset({AudioType.STEREO}),
        settings_card="qobuz",
    )
    d = _bridge(providers={"qobuz": stereo_only}, default_audio_type="both").chooserDefaults("qobuz:1", "track")
    assert d["audioOptions"] == ["stereo"]
    assert d["audioType"] == "stereo"
    assert d["audioType"] in d["audioOptions"]
    # A provider that serves Atmos keeps the stored default as it was.
    assert _bridge(default_audio_type="both").chooserDefaults("t1", "track")["audioType"] == "both"


def test_the_chooser_qml_names_no_provider():
    """Acceptance for a third provider: the popover region carries no provider
    id, name or asset, so a provider registered with a descriptor and the
    right metadata renders its segment, audio words and section gates without
    a QML edit (issue #235)."""
    import pathlib

    from waves.waves_ui import backend as backend_module

    qml = (pathlib.Path(backend_module.__file__).parent / "qml" / "Main.qml").read_text(encoding="utf-8")
    start = qml.find("id: chooserComp")
    end = qml.find("// Playlist-folder tile", start + 1)
    assert start != -1 and end != -1, "the guard found no chooser region to check"
    region = qml[start:end]
    assert "PROVIDER" in region, "the guard is looking at the wrong region"
    for needle in ("tidal", "apple", "assets/providers", "chooserRowProvider"):
        assert needle.lower() not in region.lower(), f"the Chooser region still names a provider: {needle}"


# --------------------------------------------------------------------------- #
# The search gate reads the declared capability
# --------------------------------------------------------------------------- #
def _search_stub(providers):
    stub = SimpleNamespace(
        threadpool=_InlinePool(),
        statuses=[],
        busy=[],
        _search_gen=0,
        _search_cache={},
        _objs_lock=Lock(),
        _objs={"artist": {}, "album": {}, "track": {}, "video": {}, "playlist": {}, "mix": {}},
        providers=providers,
        searchResults=_Signal(),
        artistMetaLoaded=_Signal(),
        _logged_in=True,
        settings=SimpleNamespace(data=SimpleNamespace(apple_enabled=True)),
    )
    stub.search = WavesBridge.search.__get__(stub, SimpleNamespace)
    stub._remember_search = WavesBridge._remember_search.__get__(stub, SimpleNamespace)
    stub._top_hit_dict = WavesBridge._top_hit_dict.__get__(stub, SimpleNamespace)
    stub._search_total = staticmethod(WavesBridge._search_total)
    stub._SEARCH_TTL = WavesBridge._SEARCH_TTL
    stub._SEARCH_CACHE_MAX = WavesBridge._SEARCH_CACHE_MAX
    stub._save_page_cache = lambda: None
    stub._set_status = lambda text: stub.statuses.append(text)
    stub._set_busy = lambda on: stub.busy.append(bool(on))
    stub._remember = lambda kind, key, obj: stub._objs[kind].__setitem__(key, obj)
    return stub


def test_the_search_gate_runs_only_providers_that_declare_search():
    called: list = []
    tidal = SimpleNamespace(
        name="TIDAL",
        capabilities=frozenset({Capability.SEARCH}),
        search=lambda needle: called.append("tidal") or {},
    )
    apple = SimpleNamespace(
        name="Apple Music",
        capabilities=frozenset(),
        search=lambda needle: called.append("apple") or {},
    )
    stub = _search_stub({CTX_TIDAL: tidal, CTX_APPLE: apple})

    stub.search("xtal")

    assert called == ["tidal"]

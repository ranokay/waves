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

from waves.constants import CTX_APPLE, CTX_TIDAL, QualityTier
from waves.providers import AudioType, Capability, QualityOption
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
        "_chooser_is_collection_kind",
        "_chooser_tier_entries",
        "chooserTiers",
        "chooserDefaultTier",
        "_chooser_default_tier_word",
        "_chooser_default_audio",
        "_chooser_atmos_only",
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


# --------------------------------------------------------------------------- #
# The declared metadata
# --------------------------------------------------------------------------- #
def test_the_base_metadata_defaults_are_neutral():
    from tests.test_provider_seam import _BareProvider

    bare = _BareProvider()
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
    assert d["provider"] == "apple" and d["providerFixed"] is False
    assert d["audioOptions"] == ["stereo", "atmos", "both"]
    assert d["tier"] == "LOSSLESS"
    assert d["lyricsEmbed"] is False and d["coverEmbed"] is True
    assert b.chooserDefaults("t1", "album")["providerFixed"] is True


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

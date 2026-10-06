from waves.desktop.providers.chooser import switch_choices


def defaults(**values):
    return dict(
        tier="HIGH",
        audioType="stereo",
        tiers=[{"word": "HIGH"}, {"word": "LOSSLESS"}],
        audioOptions=["stereo"],
        engine="auto",
        engines=[],
        showLyrics=True,
        showLyricsTtml=False,
        showArt=True,
        lyricsEmbed=False,
        lyricsFile=False,
        lyricsTtml=False,
        coverEmbed=True,
        coverFile=True,
        **values,
    )


def test_switch_preserves_only_compatible_explicit_choices():
    result = switch_choices(defaults(), {"tier": "LOSSLESS", "lyricsFile": True})
    assert result["values"]["tier"] == "LOSSLESS"
    assert result["values"]["lyricsFile"] is True
    assert result["values"]["audioType"] == "stereo"
    assert result["changes"] == []


def test_incompatible_mix_tier_assets_and_engine_require_confirmation():
    result = switch_choices(
        defaults(), {"tier": "HI-RES", "audioType": "both", "lyricsTtml": True, "engine": "other-provider-engine"}
    )
    assert len(result["changes"]) == 4
    assert result["values"]["tier"] == "HIGH"
    assert result["values"]["engine"] == "auto"
    assert result["explicit"] == {}


def test_explicit_off_is_preserved_for_unavailable_optional_assets():
    result = switch_choices(defaults(), {"lyricsTtml": False})
    assert result["changes"] == []
    assert result["explicit"] == {"lyricsTtml": False}


def test_unpinned_values_follow_target_defaults_and_pin_auto_is_distinct():
    target = defaults()
    target["engine"] = "saved-engine"
    assert switch_choices(target, {})["values"]["engine"] == "saved-engine"
    assert switch_choices(target, {"engine": "auto"})["values"]["engine"] == "auto"

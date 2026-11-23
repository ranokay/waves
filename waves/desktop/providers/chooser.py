"""Request-local Chooser choices; compatible pins survive a provider switch."""

type Choices = dict[str, str | bool]

CHOICE_KEYS = ("tier", "audioType", "engine", "lyricsEmbed", "lyricsFile", "lyricsTtml", "coverEmbed", "coverFile")
_ASSETS = {
    "lyricsEmbed": ("showLyrics", "Embed lyrics"),
    "lyricsFile": ("showLyrics", "Lyrics sidecar"),
    "lyricsTtml": ("showLyricsTtml", "TTML sidecar"),
    "coverEmbed": ("showArt", "Embed artwork"),
    "coverFile": ("showArt", "Artwork sidecar"),
}


def switch_choices(defaults: dict, explicit: Choices) -> dict:
    """Propose target defaults plus compatible choices, without committing them.

    Changes to an explicit requirement need the caller's confirmation. Engine
    pins belong to a provider; explicit Auto is a routing choice in its own right.
    The caller retains the old state until that confirmation succeeds.
    """
    values = {key: defaults.get(key, "auto" if key == "engine" else False) for key in CHOICE_KEYS}
    if defaults.get("atmosOnly"):
        values["audioType"] = "atmos"
    kept: Choices = {}
    changes: list[str] = []
    tiers = {entry["word"] for entry in defaults.get("tiers", [])}
    engines = {entry["id"] for entry in defaults.get("engines", [])}
    for key in CHOICE_KEYS:
        if key not in explicit:
            continue
        value = explicit[key]
        compatible = True
        label = key
        if key == "tier":
            compatible = value in tiers
            label = "Audio quality"
        elif key == "audioType":
            compatible = value in defaults.get("audioOptions", []) and (
                not defaults.get("atmosOnly") or value == "atmos"
            )
            label = "Audio type"
        elif key == "engine":
            compatible = value == "auto" or (
                value in engines
                and explicit.get("engineProvider", defaults.get("provider")) == defaults.get("provider")
            )
            label = "Engine pin"
        elif key in _ASSETS:
            capability, label = _ASSETS[key]
            compatible = value is False or bool(defaults.get(capability))
        if compatible:
            kept[key] = value
            values[key] = value
        else:
            changes.append(f"{label}: {value} → {values[key]} (unsupported by this offer)")
    if kept.get("engine") not in (None, "auto"):
        kept["engineProvider"] = str(defaults.get("provider", ""))
    return {"values": values, "explicit": kept, "changes": changes}

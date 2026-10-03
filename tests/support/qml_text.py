"""QML source scanning for the plain-text security guard.

WHAT IT PARSES
--------------
``Text``/``Label`` elements and their own ``text:``/``textFormat:``
properties, from raw .qml source. This is a character scan, not a QML parse:
it skips string literals and comments and tracks brace depth, so a property
belonging to a nested child (or a ``function() {}`` body) is never mistaken
for the element's own.

WHY A CHARACTER SCAN
--------------------
The security guard built on this module (tests/ui/test_qml_plaintext_guard.py)
must not have false negatives: a remote string on Qt's rich-text-capable
defaults is a zero-click network beacon. A regex-only property match would miss
multi-line JS blocks, ``+`` concatenations split across newlines, nested
children and strings that merely contain ``text:``; hence the scanners here
are deliberately character-level and are themselves unit-tested in
tests/ui/test_qml_text_scan.py.

HOW IT SCANS
------------
1. Enumerate every ``Text``/``Label`` open token (the lookbehind rejects
   ``TextField``, ``Foo.Text`` and friends).
2. Walk forward from its ``{`` counting depth while skipping string literals
   and comments; that balanced span is exactly the element's own source.
3. Inside the span, find a ``text:``/``textFormat:`` binding that is a direct
   property (brace-depth 1): a nested child's or a ``function(){}`` body's
   property does not count.
4. Read the value to the end of the logical statement (``;``, newline at
   depth 0, or the element's closing ``}``), continuing across newlines when
   a ``+`` joins the lines.
5. Classify: pure literals carry no identifiers; anything else is dynamic.

WHAT IT DOES NOT KNOW
---------------------
Nothing about which strings are remote or safe, and nothing about policy
(which rich-text spots are allowed). Callers own the remote markers, the
file scope and the allowlists; this module reports structure.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple


class TextElement(NamedTuple):
    """One scanned ``Text``/``Label`` element.

    ``span`` is the brace-balanced source from the element's open ``{``
    through its closing ``}``. ``marker`` is the ``guard:deliberate-richtext
    <slug>`` anchor on the open line or the line directly above, or None.
    """

    line: int
    kind: str
    span: str
    marker: str | None


# Element opens only: the lookbehind rejects ``TextField``, ``TextInput``,
# ``TextMetrics``, ``TextArea`` and ``Foo.Text`` enum reads.
_TEXT_KIND_OPEN = re.compile(r"(?<![A-Za-z0-9_.])(Text|Label)\s*\{")

# The in-source anchor for an audited rich-text element. Must sit on the
# element's open line or the line directly above it: proximity is what ties
# the audit to THIS element rather than to whatever later drifts onto some
# line number.
DELIBERATE_MARKER = re.compile(r"guard:deliberate-richtext\s+([A-Za-z0-9_-]+)")

# ``component FooText: Text {`` declarations, and files whose root element is
# a Text/Label (the file stem is then the component name).
_TEXT_DERIVED_DECLARATION = re.compile(r"(?m)^\s*component\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?:Text|Label)\s*\{")
_TEXT_ROOTED_FILE = re.compile(r"(?m)^(Text|Label)\s*\{")


def brace_span(src: str, open_brace_idx: int) -> int:  # noqa: C901 (a deliberate char/brace scanner)
    """Index of the ``}`` closing the ``{`` at ``open_brace_idx`` (strings/comments skipped)."""
    depth = 0
    i, n = open_brace_idx, len(src)
    while i < n:
        c = src[i]
        if c in "\"'":
            q = c
            i += 1
            while i < n and src[i] != q:
                if src[i] == "\\":
                    i += 1
                i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def _read_value(span: str, j: int) -> str:  # noqa: C901 (a deliberate char scanner)
    """Read a property value starting just past its colon at index ``j``.

    A bare newline at paren/bracket depth 0 normally ends the statement, EXCEPT
    when the expression is continued by a ``+`` concatenation onto the next
    line (see ``_value_continues_past_newline``); otherwise a dynamic ``text:``
    whose first line is a plain string literal (``text: "…" \\n + model.x``)
    would be read as a pure literal and skip the PlainText requirement.
    """
    n = len(span)
    while j < n and span[j] in " \t":
        j += 1
    start = j
    pdepth = 0
    last_sig = ""  # last non-whitespace char, for continuation detection
    while j < n:
        c = span[j]
        if c in "\"'":
            q = c
            j += 1
            while j < n and span[j] != q:
                if span[j] == "\\":
                    j += 1
                j += 1
            j += 1
            last_sig = q
            continue
        if c in "([{":
            pdepth += 1
            j += 1
            last_sig = c
            continue
        if c in ")]":
            pdepth -= 1
            j += 1
            last_sig = c
            continue
        if c == "}":
            if pdepth == 0:
                break
            pdepth -= 1
            j += 1
            last_sig = c
            continue
        if pdepth == 0 and c == ";":
            break
        if pdepth == 0 and c == "\n":
            if _value_continues_past_newline(span, j, last_sig):
                j += 1
                continue
            break
        if c not in " \t\r":
            last_sig = c
        j += 1
    return span[start:j]


def _value_continues_past_newline(span: str, nl_idx: int, last_sig: str) -> bool:
    """A ``text:`` binding continues when the two lines are joined by ``+``.

    QML style puts the ``+`` either trailing (``"a" +`` newline ``"b"``) or
    leading (``"a"`` newline ``+ "b"``). Truncating at the first newline is the
    evasion that let a dynamic Text whose expression continued with ``+`` on
    the next line read as a pure literal and skip the PlainText requirement,
    so both directions are checked. ``last_sig`` is the last significant
    (non-space) char seen before ``nl_idx``.
    """
    if last_sig == "+":
        return True
    k = nl_idx + 1
    n = len(span)
    while k < n and span[k] in " \t\r\n":
        k += 1
    return k < n and span[k] == "+"


def find_own_prop_value(  # noqa: C901 (a deliberate char scanner)
    span: str, prop: str
) -> str | None:
    """Value of this element's OWN ``<prop>:`` binding, or None.

    "Own" means a direct property at brace-depth 1 inside ``span``; a binding
    inside a nested child ``{...}`` or a ``function(){}`` body does not count.
    """
    n = len(span)
    plen = len(prop)
    i = 0
    depth = 0  # relative to span[0] == '{'
    while i < n:
        c = span[i]
        if c in "\"'":
            q = c
            i += 1
            while i < n and span[i] != q:
                if span[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and span[i + 1] == "/":
            while i < n and span[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and span[i + 1] == "*":
            i += 2
            while i + 1 < n and not (span[i] == "*" and span[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if c == "{":
            depth += 1
            i += 1
            continue
        if c == "}":
            depth -= 1
            i += 1
            continue
        if (
            depth == 1
            and span.startswith(prop, i)
            and re.match(re.escape(prop) + r"\s*:", span[i:])
            and (i == 0 or not (span[i - 1].isalnum() or span[i - 1] in "_."))
        ):
            j = i + plen
            while j < n and span[j] != ":":
                j += 1
            return _read_value(span, j + 1)
        i += 1
    return None


def find_own_text_value(span: str) -> str | None:
    """Value of this element's OWN ``text:`` binding (direct property), or None."""
    return find_own_prop_value(span, "text")


def iter_text_elements(source: str) -> Iterator[TextElement]:
    """Yield every ``Text``/``Label`` element in one file, in source order."""
    lines = source.splitlines()
    for m in _TEXT_KIND_OPEN.finditer(source):
        open_idx = m.end() - 1
        end_idx = brace_span(source, open_idx)
        line = source.count("\n", 0, m.start()) + 1
        marker = None
        for ln in (line, line - 1):
            if 1 <= ln <= len(lines):
                found = DELIBERATE_MARKER.search(lines[ln - 1])
                if found:
                    marker = found.group(1)
                    break
        yield TextElement(line, m.group(1), source[open_idx : end_idx + 1], marker)


def strip_string_literals(expr: str) -> str:
    """Blank the contents of ``"..."``/``'...'`` literals.

    A marker must only match a code identifier, never a word inside a quoted
    string (the literal "Search for an artist, album, or track" must not match
    ``album``). Each literal becomes one space so neighbours do not fuse.
    """
    out: list[str] = []
    i, n = 0, len(expr)
    while i < n:
        c = expr[i]
        if c in "\"'":
            q = c
            i += 1
            while i < n and expr[i] != q:
                if expr[i] == "\\":
                    i += 1
                i += 1
            i += 1  # skip the closing quote
            out.append(" ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def is_literal_only(text_value: str) -> bool:
    """True if the value is a pure literal: string/char/number/operator only.

    Such a value can never carry a remote string, so it needs no textFormat.
    Anything referencing an identifier (``model.title``, ``title``,
    ``model['x']``, an alias, ``Math.round``) is dynamic and must declare
    PlainText; no remote-vs-local guess is involved.
    """
    return re.search(r"[A-Za-z_]", strip_string_literals(text_value)) is None


def find_text_derived_components(source: str, source_name: str) -> dict[str, int]:
    """Components deriving from Text/Label in one file: name -> brace index.

    Covers ``component FooText: Text {`` declarations and files whose root
    element is a Text/Label, which contributes its file stem as the name.
    """
    found: dict[str, int] = {}
    for m in _TEXT_DERIVED_DECLARATION.finditer(source):
        found[m.group(1)] = m.end() - 1
    root = _TEXT_ROOTED_FILE.search(source)
    if root:
        found.setdefault(Path(source_name).stem, root.end() - 1)
    return found


def iter_component_opens(source: str, name: str) -> Iterator[tuple[int, int]]:
    """``(line, brace index)`` for every ``<name> {`` instantiation in source."""
    pattern = re.compile(r"(?<![A-Za-z0-9_.])" + re.escape(name) + r"\s*\{")
    for m in pattern.finditer(source):
        yield source.count("\n", 0, m.start()) + 1, m.end() - 1

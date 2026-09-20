"""Apple TTML lyrics: parse, convert, and detect timing mode.

Apple serves lyrics as TTML, the single on-wire format, with three timing
modes tagged by the ``itunes:timing`` attribute on the root ``tt`` element:
``None`` (plain unsynced text), ``Line`` (line-synced ``<p begin=...>``), and
``Word`` (syllable/word-synced ``<span begin=... end=...>`` inside each line).

Waves converts in its own layer (spec section 9.1):

- syllable TTML -> enhanced LRC (word timestamps inline as ``<mm:ss.xx>``)
- line TTML -> plain LRC (``[mm:ss.xx]`` per line)
- any TTML -> unsynced plain text (last-resort source)
- verbatim TTML is saved zero-conversion when the .ttml sidecar toggle is on

Syllable sourcing is direct: the provider calls the ``syllable-lyrics``
relationship through the embedded catalog client, never waiting on upstream
gamdl. This module never touches the network; it only converts strings.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

logger = logging.getLogger("waves.ttml_lyrics")

# TTML time expressions this converter reads: "12.34s", "00:12.34",
# "00:01:12.34", and bare seconds. Anything else reads as unknown (0.0) and
# the line keeps document order rather than failing the track.
_TIME_RE = re.compile(r"^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)s?$")


def parse_timestamp(value: object) -> float | None:
    """One TTML time expression into seconds, or None when unreadable."""
    text = str(value or "").strip()
    if not text:
        return None
    match = _TIME_RE.match(text)
    if not match:
        return None
    if match.group(2) is not None:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = float(match.group(3))
    else:
        hours = 0
        minutes = int(match.group(1) or 0) if match.group(1) else 0
        # "mm:ss.xx" vs bare seconds: a colon means minutes, else seconds.
        if ":" in text:
            seconds = float(match.group(3))
        else:
            # Bare "12.34" or "12.34s": whole value is seconds.
            try:
                return float(text.rstrip("s"))
            except ValueError:
                return None
    try:
        return float(hours * 3600 + minutes * 60 + seconds)
    except (TypeError, ValueError):
        return None


def format_lrc_timestamp(seconds: float) -> str:
    """Seconds into an LRC timestamp ``[mm:ss.xx]`` (centisecond precision)."""
    total = max(0.0, float(seconds or 0.0))
    minutes = int(total // 60)
    secs = total - minutes * 60
    return f"[{minutes:02d}:{secs:05.2f}]"


def _local(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


def _parse_root(ttml: str) -> ET.Element | None:
    """One TTML document's root, or None when empty/unparsable."""
    text = str(ttml or "")
    if not text.strip():
        return None
    try:
        return ET.fromstring(text)  # noqa: S314 (Apple-served lyrics, not untrusted XML)
    except ET.ParseError:
        return None


def _declared_timing(root: ET.Element) -> str | None:
    for key, value in root.attrib.items():
        if _local(key) == "timing":
            lowered = str(value or "").strip().lower()
            if lowered == "word":
                return "word"
            if lowered == "line":
                return "line"
            return "none"
    return None


def ttml_timing_mode(ttml: str) -> str:
    """The timing mode of a TTML document: ``word``, ``line``, or ``none``.

    Reads the ``itunes:timing`` attribute on the root element first
    (``Word``/``Line``/``None``); when absent, infers from content (any
    ``<span begin>`` means word-timed, any ``<p begin>`` means line-timed).
    Empty or unparsable input reads as ``none``.
    """
    root = _parse_root(ttml)
    if root is None:
        return "none"
    declared = _declared_timing(root)
    if declared is not None:
        return declared
    # No declared mode: infer from the body.
    if any(_local(elem.tag) == "span" and elem.get("begin") for elem in root.iter()):
        return "word"
    if any(_local(elem.tag) == "p" and elem.get("begin") for elem in root.iter()):
        return "line"
    return "none"


def _iter_paragraphs(root: ET.Element) -> list[ET.Element]:
    return [elem for elem in root.iter() if _local(elem.tag) == "p"]


def _text_of(elem: ET.Element) -> str:
    return "".join(elem.itertext()).strip()


def ttml_to_text(ttml: str) -> str:
    """Unsynced plain text out of any TTML document, one line per ``<p>``."""
    root = _parse_root(ttml)
    if root is None:
        return ""
    lines = [_text_of(p) for p in _iter_paragraphs(root)]
    return "\n".join(line for line in lines if line)


def ttml_to_lrc(ttml: str) -> str:
    """Line-level LRC out of line- or word-timed TTML.

    Each ``<p>`` becomes one ``[mm:ss.xx]`` line carrying its full text
    (word spans collapsed). Paragraphs without a readable ``begin`` keep
    document order at 0.0 rather than dropping the line.
    """
    root = _parse_root(ttml)
    if root is None:
        return ""
    out: list[str] = []
    for para in _iter_paragraphs(root):
        line = _text_of(para)
        if not line:
            continue
        begin = parse_timestamp(para.get("begin"))
        out.append(f"{format_lrc_timestamp(begin or 0.0)}{line}")
    return "\n".join(out)


def _enhanced_line(para: ET.Element) -> str:
    """One paragraph as an enhanced-LRC line, or "" when wordless."""
    line_begin = parse_timestamp(para.get("begin")) or 0.0
    spans = [child for child in list(para) if _local(child.tag) == "span"]
    if not spans:
        line = _text_of(para)
        return f"{format_lrc_timestamp(line_begin)}{line}" if line else ""
    parts: list[str] = []
    for span in spans:
        word = "".join(span.itertext())
        if not word:
            continue
        begin = parse_timestamp(span.get("begin"))
        parts.append(word if begin is None else f"<{format_lrc_timestamp(begin)[1:-1]}>{word}")
        if span.tail:
            parts.append(span.tail)
    head = str(para.text or "")
    body = "".join(parts).strip()
    line_text = f"{head}{body}".strip() if head.strip() else body
    return f"{format_lrc_timestamp(line_begin)}{line_text}" if line_text else ""


def ttml_to_enhanced_lrc(ttml: str) -> str:
    """Enhanced (word-timed) LRC out of syllable TTML.

    Each ``<p>`` becomes one line starting at its own ``begin``, with every
    word ``<span>`` stamped inline as ``<mm:ss.xx>``. Spans without a
    readable ``begin`` keep their text unstamped; a paragraph with no stamped
    spans degrades to a plain LRC line so no words are lost.
    """
    root = _parse_root(ttml)
    if root is None:
        return ""
    return "\n".join(line for para in _iter_paragraphs(root) if (line := _enhanced_line(para)))

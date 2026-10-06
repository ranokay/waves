"""Pure title canonicalization and edition vocabulary shared by metadata owners.

This module contains no local presence decisions or catalog lookup policy.
"""

from __future__ import annotations

import re
import unicodedata

# " & " / " + " and " and " are one conjunction spelled three ways (Simon &
# Garfunkel vs Simon and Garfunkel; Florence + The Machine). Whitespace is
# required on BOTH sides, which is the whole safety story: AC/DC, AT&T, "1+1"
# and Ed Sheeran's bare "+" are untouched.
_AND_RE = re.compile(r"\s(?:&|\+)\s")


def fold_conjunction(text: str) -> str:
    """Fold a free-standing ampersand or plus to the word it spells."""
    return _AND_RE.sub(" and ", text)


_VERSION_TOKEN_RE = re.compile(r"[\[(]\s*(explicit|clean|e)\s*[\])]", re.IGNORECASE)


def norm_title(title: str) -> str:
    """Title with explicit/clean markers stripped (deluxe/remaster kept) and a
    free-standing "&"/"+" folded to "and", same as artists."""
    text = fold_conjunction(_VERSION_TOKEN_RE.sub("", title or "").lower())
    return re.sub(r"\s+", " ", text).strip(" -.–—")


# --- Cross-catalog canonicalisation --------------------------------------------
# NFKC folds compatibility forms (composed vs decomposed diacritics); this table
# then folds the punctuation TIDAL and a local tagger write differently for the
# SAME release: curly vs straight quotes/apostrophes (the most common real miss)
# and the dash family to a plain hyphen. Applied to BOTH sides, so it is
# canonicalisation, not fuzzy matching, and can only fix a spurious mismatch,
# never create a match.
_CANON_PUNCT = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "…": "...",
        "–": "-",
        "—": "-",
        "‒": "-",
        "―": "-",
        "−": "-",
    }
)


# Letters the accent strip cannot reach because they never decompose: each is
# its own codepoint, not a base plus a mark. Both cases, so the fold is
# case-agnostic before the norms lowercase.
_DIACRITIC_XLIT = str.maketrans(
    {
        "ø": "o",
        "Ø": "O",
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ß": "ss",
        "ẞ": "SS",
    }
)


def _fold_diacritics(s: str) -> str:
    """Strip accents from LATIN letters only: Bjork finds Björk, Motorhead
    finds Motörhead, because the two catalogs routinely disagree on whether a
    name wears its marks. The Latin guard is load-bearing, not an
    optimisation: Japanese voicing marks (dakuten) are combining marks too,
    and a global strip would fold バ into ハ, colliding genuinely different
    kana titles and breaking the Various-Artists marker family. A mark on a
    non-Latin base is left exactly where it was."""
    out = []
    latin_base = False
    for ch in unicodedata.normalize("NFD", s):
        if unicodedata.category(ch) == "Mn":
            if latin_base:
                continue
        else:
            latin_base = ord(ch) < 0x0250
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out)).translate(_DIACRITIC_XLIT)


def canon(s: str) -> str:
    """Canonicalise a title/artist for cross-catalog comparison: NFKC, fold
    curly quotes to straight and the dash family to a hyphen, then strip
    accents from Latin letters. Symmetric on both catalogs, so it only ever
    fixes a spurious mismatch, never invents a match."""
    return _fold_diacritics(unicodedata.normalize("NFKC", s or "").translate(_CANON_PUNCT))


# --- The edition detector --------------------------------------------------------
# gate_title keeps qualifiers verbatim, which is right about WHAT they say and
# wrong about HOW catalogs spell it. Measured against a real 11k-album library:
# 2394 titles end in a qualifier, and the heaviest families are one edition in
# several coats ("Deluxe" / "Deluxe Edition" / "Deluxe Version" were 274 rows
# of the same thing; "(2011 Remaster)" and "(Remastered 2011)" likewise). A
# verbatim compare fails every cross-spelling, so a copy that IS the edition
# on screen could never be proven whenever the two catalogs dressed it
# differently.
#
# The detector reads a trailing qualifier into a SET of edition tags plus any
# years, and only for vocabulary it knows. Synonyms collapse INSIDE a class
# (filler words like "edition"/"version" carry no meaning and drop out);
# classes never collapse into each other ({deluxe} != {super, deluxe} !=
# {expanded}, and acoustic/live/instrumental never equal the studio cut). A
# tail containing ANY word it does not know is not an edition tail at all and
# stays a literal part of the title, which is what keeps "Untitled (Black Is)"
# and "Untitled (Rise)" apart: recognition can only fold spellings of the same
# thing, never two different things.

# One canonical tag per recognised edition word. Plurals and hyphen variants
# map to the same tag; "super" is its own tag so a super deluxe stays a
# different set from a deluxe.
_EDITION_TAG_WORDS = {
    "deluxe": "deluxe",
    "super": "super",
    "remaster": "remaster",
    "remastered": "remaster",
    "remasters": "remaster",
    "expanded": "expanded",
    "special": "special",
    "legacy": "legacy",
    "collector": "collector",
    "collector's": "collector",
    "collectors": "collector",
    "anniversary": "anniversary",
    "live": "live",
    "acoustic": "acoustic",
    "unplugged": "unplugged",
    "instrumental": "instrumental",
    "instrumentals": "instrumental",
    "demo": "demo",
    "demos": "demo",
    "mono": "mono",
    "stereo": "stereo",
    "reissue": "reissue",
    "re-issue": "reissue",
    "rerelease": "reissue",
    "re-release": "reissue",
    "stripped": "stripped",
    "reimagined": "reimagined",
    "redux": "redux",
    "bonus": "bonus",
}
# Words that shape the phrase but not the release: "Deluxe Edition", "Deluxe
# Version" and "Deluxe" are one edition. "track(s)" is here for "Bonus Track
# Version"; a tail of nothing but filler has no tag word and stays literal.
_EDITION_FILLER_WORDS = {"edition", "version", "the", "and", "track", "tracks"}
_EDITION_YEAR_RE = re.compile(r"^(19|20)\d\d$")
# "20th" in "20th Anniversary": the ordinal is part of WHICH edition it is,
# so it joins the tag set and a 20th never equals a 25th.
_EDITION_ORDINAL_RE = re.compile(r"^\d+(st|nd|rd|th)$")
# The same trailing-group shape strip_edition_quals peels, and the dash form
# some taggers use instead ("Album - Deluxe Edition"). The dash tail is only
# ever an edition here if every word parses, so "Live - 1970" stays literal.
_EDITION_TAIL_PAREN_RE = re.compile(r"\s*[\(\[]([^\)\]]*)[\)\]]\s*$")
_EDITION_TAIL_DASH_RE = re.compile(r"\s+-\s+([^-]+)$")


def _parse_edition_tail(tail: str) -> tuple[frozenset[str], frozenset[int]] | None:
    """One trailing group as ``(tags, years)``, or None when any word in it is
    not recognised edition vocabulary (the tail is then part of the title).
    Segments ("Deluxe Edition/Remastered") merge into one set: the qualifier
    describes one release however it punctuates."""
    tags: set[str] = set()
    years: set[int] = set()
    words = re.split(r"[\s/;,+]+", tail.strip().lower())
    for word in words:
        word = word.strip(".'\"")
        if not word:
            continue
        if word in _EDITION_TAG_WORDS:
            tags.add(_EDITION_TAG_WORDS[word])
        elif _EDITION_ORDINAL_RE.match(word):
            tags.add(word)
        elif _EDITION_YEAR_RE.match(word):
            years.add(int(word))
        elif word not in _EDITION_FILLER_WORDS:
            return None
    if not tags:
        # Years or filler alone ("(2015 Edition)", "(1970)") name something
        # this vocabulary cannot identify; keeping them literal is the safe
        # direction.
        return None
    return frozenset(tags), frozenset(years)


def edition_key(title: str) -> tuple[str, frozenset[str], frozenset[int]]:
    """``(base, tags, years)`` for a gate-normalised title: every trailing
    group that parses as edition vocabulary is folded into the tag set, and
    the first one that does not stops the peel and stays in the base."""
    text = norm_title(canon(title))
    tags: frozenset[str] = frozenset()
    years: frozenset[int] = frozenset()
    while True:
        m = _EDITION_TAIL_PAREN_RE.search(text) or _EDITION_TAIL_DASH_RE.search(text)
        if not m:
            break
        parsed = _parse_edition_tail(m.group(1))
        if parsed is None:
            break
        tags |= parsed[0]
        years |= parsed[1]
        text = text[: m.start()].rstrip(" -.")
    return text, tags, years

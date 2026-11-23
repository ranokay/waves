"""The cross-catalog text key: canonicalise, casefold, collapse whitespace."""

from __future__ import annotations

from waves.metadata.title_identity import canon_text


def test_canonical_text_folds_curly_quotes_and_accents_across_catalogs() -> None:
    assert canon_text("  Björk’s  Choir ") == "bjork's choir"


def test_canonical_text_collapses_whitespace_without_inventing_word_folds() -> None:
    # "&" folds to "and" through norm_title/edition_key (titles); the bare
    # canonical text stays the conservative key the identity comparisons use.
    assert canon_text("Simon\t&\nGarfunkel") == "simon & garfunkel"


def test_canonical_text_is_stable_for_empty_input() -> None:
    assert canon_text("") == ""
    assert canon_text("   ") == ""

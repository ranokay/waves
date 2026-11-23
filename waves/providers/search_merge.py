"""Fold provider search groups into one labelled display surface.

Provider-neutral: rows are the shared schema in ``providers/base.py``,
whatever provider built them, and the decision uses catalog evidence alone.
High-confidence equivalents fold into one row that exposes every source;
everything less stays separate, labelled with its own source. Display-only:
no lookup, no network, no cache writes, and the input groups (which the
search cache retains) are never mutated.
"""

from __future__ import annotations

from waves.metadata.catalog_identity import catalog_identifier
from waves.metadata.title_identity import canon_text, edition_key

SECTIONS: tuple[str, ...] = ("artists", "albums", "tracks", "videos", "playlists", "mixes")
_MERGE_KINDS = frozenset({"albums", "tracks"})


def _agrees(left, right) -> bool:
    """Non-empty canonical text equal on both sides. Empty is a missing
    fact, never a match."""
    left_text = canon_text(str(left or ""))
    return bool(left_text) and left_text == canon_text(str(right or ""))


def _same_title(left, right) -> bool:
    """One edition-key title: the qualifier vocabulary distinguishes a
    remaster or deluxe from its base release even when the ISRC was reused."""
    left_text = edition_key(str(left or ""))
    return bool(left_text[0]) and left_text == edition_key(str(right or ""))


def _nearby_seconds(left: dict, right: dict) -> bool:
    """Raw catalog durations agree within the coarsest catalog precision."""
    try:
        left_seconds = int(left.get("duration_sec") or 0)
        right_seconds = int(right.get("duration_sec") or 0)
    except (TypeError, ValueError):
        return False
    return left_seconds > 0 and right_seconds > 0 and abs(left_seconds - right_seconds) <= 1


def _tracks_equivalent(left: dict, right: dict) -> bool:
    identifier = catalog_identifier("track", str(left.get("isrc") or ""))
    if not identifier or identifier != catalog_identifier("track", str(right.get("isrc") or "")):
        return False
    return (
        _same_title(left.get("title", ""), right.get("title", ""))
        and _agrees(left.get("artist", ""), right.get("artist", ""))
        and _nearby_seconds(left, right)
        and bool(left.get("explicit")) == bool(right.get("explicit"))
    )


def _albums_equivalent(left: dict, right: dict) -> bool:
    identifier = catalog_identifier("album", str(left.get("upc") or ""))
    if not identifier or identifier != catalog_identifier("album", str(right.get("upc") or "")):
        return False
    try:
        left_count = int(left.get("tracks") or 0)
        right_count = int(right.get("tracks") or 0)
    except (TypeError, ValueError):
        return False
    return (
        _same_title(left.get("title", ""), right.get("title", ""))
        and _agrees(left.get("artist", ""), right.get("artist", ""))
        and left_count > 0
        and left_count == right_count
        and bool(left.get("explicit")) == bool(right.get("explicit"))
    )


_EQUIVALENT = {"albums": _albums_equivalent, "tracks": _tracks_equivalent}


def _source(provider: str, row: dict) -> dict:
    return {"provider": str(provider), "id": str(row.get("id", ""))}


def _mergeable(name: str, groups: list[dict]) -> list[dict]:
    equivalent = _EQUIVALENT[name]
    items: list[dict] = []
    for group in groups:
        provider = str(group.get("provider", ""))
        for row in group.get(name) or []:
            if not isinstance(row, dict):
                continue
            for item in items:
                # A fold is a cross-provider claim: a provider's own duplicate
                # reply stays two labelled rows.
                if equivalent(item["row"], row) and not any(
                    source["provider"] == provider for source in item["sources"]
                ):
                    item["sources"].append(_source(provider, row))
                    break
            else:
                items.append({"row": dict(row), "sources": [_source(provider, row)]})
    return [{**item["row"], "sources": item["sources"]} for item in items]


def _labelled(name: str, groups: list[dict]) -> list[dict]:
    return [
        {**row, "sources": [_source(str(group.get("provider", "")), row)]}
        for group in groups
        for row in group.get(name) or []
        if isinstance(row, dict)
    ]


def fold_search_groups(groups: list[dict]) -> dict:
    """The unified display view of the arrived provider groups.

    ``groups`` is in display order (an earlier group's row is the one that
    stays; later equivalents only add sources). Returns ``sections`` for the
    buckets any arrived provider answers and the first provider's ``top``
    pin, whose sources mirror the row it points at.
    """
    arrived = [group for group in (groups or []) if isinstance(group, dict)]
    sections: dict[str, list[dict]] = {}
    for name in SECTIONS:
        present = [group for group in arrived if name in group]
        if not present:
            continue
        sections[name] = _mergeable(name, present) if name in _MERGE_KINDS else _labelled(name, present)
    top = None
    for group in arrived:
        row = group.get("top")
        if isinstance(row, dict):
            top = {**row, "sources": [_source(str(group.get("provider", "")), row)]}
            break
    if top is not None:
        # The pin is a pointer to a row, not a copy: a row that folded with
        # an equivalent exposes the same sources from the pin.
        name = "tracks" if top.get("kind") == "track" else "albums" if top.get("kind") == "album" else ""
        if name:
            for row in sections.get(name) or []:
                if row.get("id") == top.get("id") or _EQUIVALENT[name](row, top):
                    top["sources"] = row["sources"]
                    break
    return {"sections": sections, "top": top}

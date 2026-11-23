"""Bounded catalog evidence, separate from Library presence and file integrity.

Raw catalog durations are compared within one second (the coarsest supported
catalog precision). Display lengths and unknown explicit/version facts cannot
authorize substitution. Results are immutable snapshots, never a universal ID.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
from time import time

from waves.ids import namespaced_id
from waves.metadata.title_identity import canon_text, edition_key

MAX_CANDIDATES = 10
MAX_TRACKS = 200
MAX_ENTRIES = 64


class MatchState(StrEnum):
    HIGH_CONFIDENCE = "high_confidence"
    USER_CONFIRMED = "user_confirmed"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class CatalogIdentity:
    media_id: str
    kind: str
    title: str = ""
    artist: str = ""
    # ISRC for audio; UPC for a release. Video has no automatic identity rule.
    identifier: str = ""
    duration_ms: int | None = None
    explicit: bool | None = None
    # None means unknown; empty means a catalog title with no extra qualifier.
    version: str | None = None
    release_title: str = ""
    release_version: str | None = None
    release_artist: str = ""
    release_date: str = ""
    release_upc: str = ""
    track_number: int | None = None
    disc_number: int | None = None
    track_count: int | None = None
    tracks: tuple[CatalogIdentity, ...] = ()
    tracks_complete: bool = False

    def __post_init__(self) -> None:
        if not self.media_id or ":" not in self.media_id or not all(self.media_id.split(":", 1)):
            message = "Catalog evidence needs a namespaced media ID"
            raise ValueError(message)


@dataclass(frozen=True)
class CatalogLookup:
    candidates: tuple[CatalogIdentity, ...] = ()
    complete: bool = True
    explanations: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchEvidence:
    identity: CatalogIdentity
    missing: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    @property
    def consistent(self) -> bool:
        return not self.missing and not self.conflicts


@dataclass(frozen=True)
class CatalogResolution:
    origin_id: str
    state: MatchState
    candidates: tuple[MatchEvidence, ...] = ()
    explanations: tuple[str, ...] = ()
    confirmed_id: str = ""
    observed_at: float = 0

    @property
    def automatic_eligible(self) -> bool:
        return self.state == MatchState.HIGH_CONFIDENCE

    def confirm(self, media_id: str) -> CatalogResolution:
        """Review applies to this snapshot only, never to automatic routing."""
        media_id = namespaced_id(media_id)
        if not any(item.identity.media_id == media_id for item in self.candidates):
            message = "Confirmation must select an observed candidate"
            raise ValueError(message)
        return replace(
            self,
            state=MatchState.USER_CONFIRMED,
            confirmed_id=media_id,
            explanations=(
                *self.explanations,
                "Explicitly reviewed for this request; automatic routing remains ineligible.",
            ),
        )


def _text(value: str) -> str:
    return canon_text(value)


def _release_version(title: str) -> tuple[frozenset[str], frozenset[int]]:
    """Retain master/mix warnings even outside a parseable edition suffix."""
    _, tags, years = edition_key(title)
    text = _text(title)
    sensitive = frozenset(
        {
            "remaster",
            "live",
            "mono",
            "stereo",
            "acoustic",
            "unplugged",
            "instrumental",
            "demo",
            "reimagined",
            "redux",
            "stripped",
        }
    )
    markers = tags & sensitive
    for pattern, marker in (
        (r"\bremaster(?:ed|s)?\b", "remaster"),
        (r"\bremix(?:ed)?\b", "remix"),
        (r"\bre[ -]?record(?:ed|ing)?\b|taylor'?s version", "rerecord"),
    ):
        if re.search(pattern, text):
            markers |= {marker}
    # Edition parsing deliberately leaves free-form qualifiers literal.
    # Retain those details whenever they declare a different performance/mix.
    marker_pattern = r"\b(?:live|acoustic|unplugged|instrumentals?|demos?|mono|stereo|stripped|reimagined|redux|remaster(?:ed|s)?|remix(?:ed)?|re[ -]?record(?:ed|ing)?)\b|taylor'?s version"
    phrases = re.findall(r"[\(\[]([^\)\]]+)[\)\]]", text)
    phrases.append(re.sub(r"[\(\[][^\)\]]*[\)\]]", "", text).strip())
    for phrase in phrases:
        if re.search(marker_pattern, phrase):
            base, phrase_tags, phrase_years = edition_key(f"context ({phrase})")
            markers |= phrase_tags & sensitive
            years |= phrase_years
            if base != "context":
                markers |= {f"context:{phrase}"}
    if "remaster" in markers:
        years |= frozenset(int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", text))
    return markers, years if markers else frozenset()


def _release_date(value: str) -> str:
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return ""


def _release_title(identity: CatalogIdentity) -> str:
    return (
        f"{identity.release_title} ({identity.release_version})" if identity.release_version else identity.release_title
    )


def catalog_identifier(kind: str, value: str) -> str:
    """Canonical supported identifiers; malformed values remain missing."""
    value = value.strip().upper().replace("-", "")
    if kind == "track":
        return value if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}[0-9]{7}", value) else ""
    if kind == "album":
        if not re.fullmatch(r"[0-9]{12,14}", value):
            return ""
        padded = value.zfill(14)
        checksum = sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(padded[:-1]))
        return padded if (checksum + int(padded[-1])) % 10 == 0 else ""
    return ""


@dataclass
class _Comparison:
    origin: CatalogIdentity
    candidate: CatalogIdentity
    missing: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def fact(self, label: str, left: str | int | bool | None, right: str | int | bool | None) -> None:
        if left is None or right is None or left == "" or right == "":
            self.missing.append(label)
        elif left != right:
            self.conflicts.append(label)

    def recording(self) -> None:
        origin, candidate = self.origin, self.candidate
        if not origin.duration_ms or not candidate.duration_ms or min(origin.duration_ms, candidate.duration_ms) <= 0:
            self.missing.append("precise duration")
        elif abs(origin.duration_ms - candidate.duration_ms) > 1000:
            self.conflicts.append("precise duration")
        if (
            not origin.release_title
            or not candidate.release_title
            or origin.release_version is None
            or candidate.release_version is None
        ):
            self.missing.append("release version context")
        else:
            # Recording equivalence may span albums, but a declared remaster
            # cannot disappear just because its ISRC was reused.
            left = _release_title(origin)
            right = _release_title(candidate)
            if _release_version(left) != _release_version(right):
                self.conflicts.append("release version/remaster")

    def release(self) -> None:
        origin, candidate = self.origin, self.candidate
        if (
            not origin.release_title
            or not candidate.release_title
            or origin.release_version is None
            or candidate.release_version is None
        ):
            self.missing.append("release Edition")
        elif edition_key(_release_title(origin)) != edition_key(_release_title(candidate)):
            self.conflicts.append("release Edition")
        self.fact("release artist", _text(origin.release_artist), _text(candidate.release_artist))
        self.fact("release date", _release_date(origin.release_date), _release_date(candidate.release_date))
        self.fact(
            "release UPC",
            catalog_identifier("album", origin.release_upc),
            catalog_identifier("album", candidate.release_upc),
        )
        self.fact("release track count", origin.track_count, candidate.track_count)
        if origin.kind == "track":
            self.fact("track position", origin.track_number, candidate.track_number)
            self.fact("disc position", origin.disc_number, candidate.disc_number)

    def ordered_tracks(self) -> None:
        origin, candidate = self.origin, self.candidate
        for release in (origin, candidate):
            if release.explicit is False and any(track.explicit is True for track in release.tracks[:MAX_TRACKS]):
                self.conflicts.append("release explicitness contradicts track list")
        if not origin.tracks_complete or not candidate.tracks_complete or not origin.tracks or not candidate.tracks:
            self.missing.append("complete ordered track list")
        if origin.track_count != len(origin.tracks) or candidate.track_count != len(candidate.tracks):
            self.missing.append("declared ordered track count")
        if len(origin.tracks) != len(candidate.tracks):
            self.conflicts.append("ordered track list length")
        if max(len(origin.tracks), len(candidate.tracks)) > MAX_TRACKS:
            self.missing.append("track list exceeds selected-context bound")
        for index, (left, right) in enumerate(
            zip(origin.tracks[:MAX_TRACKS], candidate.tracks[:MAX_TRACKS], strict=False), 1
        ):
            evidence = compare_identity(left, right)
            self.missing.extend(f"track {index}: {item}" for item in evidence.missing)
            self.conflicts.extend(f"track {index}: {item}" for item in evidence.conflicts)
            self.fact(f"track {index} position", left.track_number, right.track_number)
            self.fact(f"track {index} disc", left.disc_number, right.disc_number)


def compare_identity(origin: CatalogIdentity, candidate: CatalogIdentity, policy: str = "recording") -> MatchEvidence:
    """Compare facts without ranking, fuzzy promotion, or provider branches."""
    comparison = _Comparison(origin, candidate)
    if origin.kind != candidate.kind:
        comparison.conflicts.append("media kind")
    if origin.kind not in ("track", "album"):
        comparison.missing.append("supported media identity (audio does not prove video equivalence)")
    else:
        comparison.fact(
            "identifier",
            catalog_identifier(origin.kind, origin.identifier),
            catalog_identifier(candidate.kind, candidate.identifier),
        )
        comparison.fact("title", _text(origin.title), _text(candidate.title))
        comparison.fact("artist", _text(origin.artist), _text(candidate.artist))
        comparison.fact("explicitness", origin.explicit, candidate.explicit)
        if origin.version is None or candidate.version is None:
            comparison.missing.append("version")
        elif _text(origin.version) != _text(candidate.version):
            comparison.conflicts.append("version")
        if origin.kind == "track":
            comparison.recording()
        if origin.kind == "album" or policy == "release":
            comparison.release()
        if origin.kind == "album":
            comparison.ordered_tracks()
    return MatchEvidence(candidate, tuple(comparison.missing), tuple(comparison.conflicts))


def resolve_candidates(origin: CatalogIdentity, lookup: CatalogLookup, policy: str = "recording") -> CatalogResolution:
    """Only one fully evidenced, uncontradicted candidate qualifies automatically."""
    if policy not in ("recording", "release"):
        message = "Unknown persisted matching policy"
        raise ValueError(message)
    # Exact duplicate provider responses are harmless; divergent facts under
    # the same ID remain visible as a collision. Source entries are never deduped.
    candidates = tuple(dict.fromkeys(lookup.candidates[:MAX_CANDIDATES]))
    evidence = tuple(compare_identity(origin, item, policy) for item in candidates[:MAX_CANDIDATES])
    explanations = list(lookup.explanations)
    complete = lookup.complete and len(lookup.candidates) <= MAX_CANDIDATES
    if not complete:
        explanations.append("Candidate lookup is incomplete or exceeded its bound.")
    identifier = catalog_identifier(origin.kind, origin.identifier)
    collision = bool(identifier) and any(
        catalog_identifier(item.identity.kind, item.identity.identifier) == identifier and item.conflicts
        for item in evidence
    )
    if collision:
        explanations.append("Identifier collision: contradictory catalog facts block automatic eligibility.")
    for item in evidence:
        if item.missing:
            explanations.append(f"{item.identity.media_id}: missing {', '.join(item.missing)}.")
        if item.conflicts:
            explanations.append(f"{item.identity.media_id}: conflicting {', '.join(item.conflicts)}.")
    if len(evidence) == 1 and evidence[0].consistent and complete and not collision:
        state = MatchState.HIGH_CONFIDENCE
        explanations.append("Identifier and required catalog facts agree.")
    elif len(evidence) > 1 or collision:
        state = MatchState.AMBIGUOUS
        explanations.append("Competing or contradictory candidates require review.")
    else:
        state = MatchState.UNRESOLVED
        explanations.append("No uniquely evidenced equivalent is available.")
    return CatalogResolution(origin.media_id, state, evidence, tuple(explanations), observed_at=time())

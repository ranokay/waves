"""The duplicate decision both download engines ask, and Keep-both naming.

ADR 0011: one duplicate policy per batch -- Keep existing (default), Replace
Waves-owned, or Keep both. ``refresh_own`` is the internal value the legacy
"Skip existing off" toggle captures; it keeps that toggle's historical
identity answer (an untagged own copy is still this track's) while adding tag
carry-over. The strict "confidently owned and unchanged" rule belongs only to
the user-chosen Replace policy and to an explicit upgrade.

Nothing here touches the filesystem except the naming helper's existence
checks; the engines own the placement itself.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

RETAINED_REASON = "Kept existing copy: below the requested minimum"
PROTECTED_REASON = "Existing file kept: not a proven Waves-owned unchanged copy"
UPGRADE_RETAINED_REASON = "Kept existing copy: the delivery did not prove an upgrade"
CARRY_OVER_FAILED_REASON = "Kept existing copy: its user tags could not be carried over"

USER_POLICIES = ("keep_existing", "replace_owned", "keep_both")
INTERNAL_POLICIES = ("refresh_own",)
ALL_POLICIES = USER_POLICIES + INTERNAL_POLICIES

# The library scan's coarse local quality classes, on the Waves ladder.
LOCAL_CLASS_RANK = {"low": 0, "high": 1, "lossless": 2, "hires": 3}


def claim_meets_minimum(claim, target_rank: int) -> bool:
    """Whether a library-scan claim's local copy meets a requested minimum."""
    local = str(claim.get("local_class") or "").strip().lower() if isinstance(claim, dict) else ""
    return LOCAL_CLASS_RANK.get(local, -1) >= int(target_rank)


def retains_below_minimum(policy: str, strategy: str, recorded_rank: int, target_rank: int) -> bool:
    """Keep existing + a required minimum keeps a below-minimum copy.

    The one rule both engines' pre-fetch gates ask; a best-available policy
    keeps its historical same-provider upgrade behaviour instead.
    """
    return policy == "keep_existing" and strategy == "minimum_required" and int(recorded_rank) < int(target_rank)


@dataclass(frozen=True)
class ExistingCopy:
    """What the destination already holds, from the engine's own gate."""

    path: str = ""
    owned: bool = False
    same_item: bool = False
    same_version: bool = False
    unchanged: bool | None = None
    current: bool = False
    minimum_met: bool = True


@dataclass(frozen=True)
class PlacementDecision:
    """What to do with the destination: download, skip, replace or land beside."""

    action: str
    reason: str = ""
    overwrite: bool = False
    readable_suffix: bool = False


def decide_placement(
    policy: str,
    existing: ExistingCopy | None,
    *,
    minimum_required: bool = False,
) -> PlacementDecision:
    """The one duplicate-policy decision, shared by TIDAL and Apple."""
    if existing is None or not existing.path:
        return PlacementDecision("download")
    policy = policy if policy in ALL_POLICIES else "keep_existing"
    if policy == "keep_existing":
        if minimum_required and not existing.minimum_met:
            return PlacementDecision("retain", RETAINED_REASON)
        if existing.current:
            return PlacementDecision("skip")
        return PlacementDecision("download")
    if policy == "refresh_own":
        if existing.same_item and existing.same_version:
            return PlacementDecision("replace", overwrite=True)
        # A different track holds the name: the historical numbered step-aside.
        return PlacementDecision("keep_both")
    if policy == "replace_owned":
        if existing.owned and existing.same_item and existing.same_version and existing.unchanged:
            return PlacementDecision("replace", overwrite=True)
        return PlacementDecision("keep_both", PROTECTED_REASON, readable_suffix=True)
    # keep_both
    return PlacementDecision("keep_both", readable_suffix=True)


def keep_both_suffix(provider: str = "", quality: str = "", audio_type: str = "") -> str:
    """A readable, filesystem-valid suffix naming what this copy is."""
    from waves.paths import sanitize_name_component

    parts = [str(part or "").strip() for part in (provider, quality, audio_type)]
    text = " ".join(part for part in parts if part)
    # Sanitize the inner text, then add the separator space the name formatter
    # would otherwise trim away.
    return f" [{sanitize_name_component(text or 'copy')}]"


def keep_both_name(
    path: str | pathlib.Path,
    *,
    provider: str = "",
    quality: str = "",
    audio_type: str = "",
    taken: set[str] | None = None,
) -> pathlib.Path | None:
    """A free Keep-both name: the readable suffix, then a collision counter."""
    from waves.paths import name_comparison_key, unique_variant_name

    base = pathlib.Path(path)
    suffix = keep_both_suffix(provider, quality, audio_type)
    # ``taken`` carries full path strings from the engine's claim registry;
    # compare the NAME the filesystem would see, not the whole path.
    occupied = {name_comparison_key(pathlib.Path(name).name) for name in taken or ()}
    for count in range(1, 100):
        candidate_suffix = suffix if count == 1 else f"{suffix} [{count}]"
        name = unique_variant_name(base, candidate_suffix)
        if name_comparison_key(name) in occupied:
            continue
        if (base.parent / name).exists():
            continue
        return base.parent / name
    return None

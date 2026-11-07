"""Opt-in cross-provider Version upgrade: verify first, commit atomically.

ADR 0011 allows an upgrade only when the existing Version is a confidently
Waves-owned unchanged file of the same recording and audio type, the matched
offer demonstrates an improvement under the ADR 0001 ranking, and the delivered
file proves that improvement before anything is committed. Any failure leaves
the existing file and its ownership row intact.

The file commit here never depends on hard links: a same-folder copy is the
fallback, and when neither backup can be made the upgrade aborts.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import shutil
from dataclasses import asdict, dataclass
from uuid import uuid4

from waves.metadata.digest import digest_matches
from waves.providers.catalog_offers import DeliveryFacts, compare_quality


@dataclass(frozen=True)
class UpgradePlan:
    """What an eligible upgrade would replace, and the facts it must beat."""

    origin_id: str
    origin_path: str
    audio_type: str
    recorded: DeliveryFacts
    delivered_provider: str = ""
    delivered_media_id: str = ""
    origin_digest: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "origin_id": self.origin_id,
                "origin_path": self.origin_path,
                "audio_type": self.audio_type,
                "recorded": asdict(self.recorded),
                "delivered_provider": self.delivered_provider,
                "delivered_media_id": self.delivered_media_id,
                "origin_digest": self.origin_digest,
            }
        )

    @classmethod
    def from_json(cls, text: str | None) -> UpgradePlan | None:
        if not text:
            return None
        try:
            raw = json.loads(text)
            if not isinstance(raw, dict):
                return None
            recorded = raw.get("recorded") or {}
            return cls(
                origin_id=str(raw.get("origin_id") or ""),
                origin_path=str(raw.get("origin_path") or ""),
                audio_type=str(raw.get("audio_type") or ""),
                recorded=DeliveryFacts(
                    tier=recorded.get("tier"),
                    audio_type=str(recorded.get("audio_type") or ""),
                    codec=str(recorded.get("codec") or ""),
                    profile=str(recorded.get("profile") or ""),
                    sample_rate=recorded.get("sample_rate"),
                    bit_depth=recorded.get("bit_depth"),
                    bitrate=recorded.get("bitrate"),
                    width=recorded.get("width"),
                    height=recorded.get("height"),
                    hdr=recorded.get("hdr"),
                    frame_rate=recorded.get("frame_rate"),
                ),
                delivered_provider=str(raw.get("delivered_provider") or ""),
                delivered_media_id=str(raw.get("delivered_media_id") or ""),
                origin_digest=str(raw.get("origin_digest") or ""),
            )
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class UpgradeResult:
    ok: bool
    path: pathlib.Path | None = None
    reason: str = ""


def upgrade_eligible(plan: UpgradePlan, delivered: DeliveryFacts) -> bool:
    """Whether the delivered facts demonstrably beat the recorded ones.

    The planned and delivered audio types must both be known and equal: a
    delivery that does not say what audio it is cannot be proven the same
    audio type the plan was made for.
    """
    if not plan.audio_type or delivered.audio_type != plan.audio_type:
        return False
    return compare_quality(delivered, plan.recorded) == 1


def _backup_path(origin: pathlib.Path) -> pathlib.Path:
    return origin.with_name(f".{origin.name}.waves-upgrade-{uuid4().hex[:8]}")


def _make_backup(origin: pathlib.Path) -> pathlib.Path | None:
    """A same-folder backup: hard link first, copy second, None on refusal."""
    backup = _backup_path(origin)
    try:
        os.link(origin, backup)
    except OSError:
        pass
    else:
        return backup
    try:
        shutil.copy2(origin, backup)
    except OSError:
        return None
    return backup


def commit_upgrade(  # noqa: C901 - verify, place, record and restore in one commit
    staged: pathlib.Path,
    plan: UpgradePlan,
    delivered: DeliveryFacts,
    *,
    place,
    record,
    final_suffix: str = "",
) -> UpgradeResult:
    """Place a verified replacement and record it, restoring on any failure.

    ``place(staged, final)`` must be atomic (a rename/swap, never a partial
    write under the final name). ``record(final)`` must write the ownership
    replacement transactionally. ``final_suffix`` is the delivered container's
    extension; the staged temp file may have no extension at all. A failure in
    either restores the origin file and leaves the row untouched; the caller
    drops the staged bytes. A cross-container final name that already holds a
    file is never overwritten or deleted: the upgrade reports retained.
    """
    if not upgrade_eligible(plan, delivered):
        return UpgradeResult(False, None, "The delivery did not prove an upgrade")
    origin = pathlib.Path(plan.origin_path)
    if plan.origin_digest and not digest_matches(plan.origin_digest, origin):
        # The file changed after the plan was captured: never overwrite a
        # copy that is no longer the one the user consented to replace.
        return UpgradeResult(False, None, "The existing copy changed")
    suffix = final_suffix or staged.suffix
    final = origin if suffix.lower() == origin.suffix.lower() else origin.with_suffix(suffix)
    if final != origin and final.exists():
        return UpgradeResult(False, None, "The replacement name is occupied")
    backup: pathlib.Path | None = None
    if final == origin:
        backup = _make_backup(origin)
        if backup is None:
            return UpgradeResult(False, None, "Could not back up the existing file")
    placed = False
    try:
        placed = bool(place(staged, final))
        if not placed:
            return UpgradeResult(False, None, "The replacement could not be placed")
        record(final)
    except Exception as exc:
        if backup is not None:
            with contextlib.suppress(OSError):
                os.replace(backup, origin)
            backup = None
        elif placed and final != origin:
            with contextlib.suppress(OSError):
                final.unlink()
        return UpgradeResult(False, None, str(exc) or "The replacement could not be committed")
    finally:
        if backup is not None:
            with contextlib.suppress(OSError):
                backup.unlink()
    if final != origin:
        with contextlib.suppress(OSError):
            origin.unlink()
    return UpgradeResult(True, final)

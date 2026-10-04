"""Disposable provider snapshots: stage outside locks, publish under epochs.

The bridge supplies account stamps and owns attribution on restore. This
module preserves its page/search layout and never treats an empty stamp as
proof of an account. Each file is atomic; the two files are independent.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from _thread import LockType
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from waves.desktop.providers.lifecycle import ProviderContexts, ProviderToken, page_provider
from waves.ids import DEFAULT_PROVIDER, provider_of_id

logger = logging.getLogger(__name__)

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type Snapshot = dict[str, JsonValue]

# v7 mixed providers under one TIDAL user. Its account attribution is unsafe
# to restore; v8 carries the bridge's per-provider opaque ``accounts`` stamps.
SNAPSHOT_VERSION = 8


class _SnapshotHost(Protocol):
    _page_cache_path: str | Path
    _search_cache_path: str | Path
    _page_cache_lock: LockType
    _provider_contexts: ProviderContexts


def remove_provider(data: Mapping[str, JsonValue], provider_id: str) -> Snapshot:
    """Copy a snapshot without one owner's fields or mixed search entries."""
    result = dict(data)
    if provider_id == DEFAULT_PROVIDER and "browse_root" in result:
        result["browse_root"] = None
    owners: tuple[tuple[str, Callable[[str], str]], ...] = (
        ("browse_pages", page_provider),
        ("artists", provider_of_id),
        ("library", lambda key: key.partition(":")[0]),
        ("home", lambda key: key),
        ("accounts", lambda key: key),
    )
    for field, owner in owners:
        entries = data.get(field)
        if isinstance(entries, dict):
            result[field] = {key: value for key, value in entries.items() if owner(key) != provider_id}
    searches = data.get("searches")
    if isinstance(searches, dict):
        retained: Snapshot = {}
        for key, payload in searches.items():
            groups = payload.get("groups") if isinstance(payload, dict) else None
            if provider_id in key.partition(":")[0].split("+") or (
                isinstance(groups, list)
                and any(isinstance(group, dict) and group.get("provider") == provider_id for group in groups)
            ):
                continue
            retained[key] = payload
        result["searches"] = retained
    return result


def _stage(path: Path, serialized: str) -> Path:
    """Write this save's private sibling completely before any commit lock."""
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    staged = Path(name)
    complete = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        complete = True
    finally:
        if not complete:
            with contextlib.suppress(OSError):
                staged.unlink(missing_ok=True)
    return staged


def save_snapshot(
    bridge: _SnapshotHost,
    data: Mapping[str, JsonValue],
    searches: Mapping[str, JsonValue],
    tokens: Sequence[ProviderToken],
) -> bool:
    """Publish only if every participating provider still owns its epoch.

    Callers capture tokens before reading caches and supply ``accounts`` in
    each payload. Serialization, temporary writes and fsync run outside both
    locks. The existing context RLock guards the complete token check and the
    short final replacements under the snapshot writer lock. A revoked save
    cannot recreate a snapshot removed after sign-out.
    """
    captured = tuple(tokens)
    if not captured or getattr(bridge, "_factory_reset", False):
        return False
    staged: list[tuple[Path, Path]] = []
    committed = False
    try:
        for path, payload in (
            (Path(bridge._page_cache_path), data),
            (Path(bridge._search_cache_path), searches),
        ):
            serialized = json.dumps({**payload, "version": SNAPSHOT_VERSION}, allow_nan=False)
            staged.append((_stage(path, serialized), path))

        def publish() -> None:
            nonlocal committed
            # commit() holds the context authority's RLock, so checking the
            # remaining tokens cannot race another provider's revocation.
            if getattr(bridge, "_factory_reset", False) or not all(
                bridge._provider_contexts.current(token) for token in captured
            ):
                return
            with bridge._page_cache_lock:
                for temporary, destination in staged:
                    os.replace(temporary, destination)
            committed = True

        bridge._provider_contexts.commit(captured[0], publish)
    except (OSError, TypeError, ValueError, RuntimeError):
        logger.debug("Provider snapshot save skipped", exc_info=True)
    finally:
        for temporary, _destination in staged:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
    return committed


def read_snapshot(path: str | Path) -> Snapshot:
    """Parse outside locks; the caller guards matching-account restoration."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        logger.debug("Provider snapshot read skipped", exc_info=True)
        return {}
    if not isinstance(data, dict) or data.get("version") != SNAPSHOT_VERSION:
        return {}
    return cast(Snapshot, data)

"""Persistent notification history: one redacted entry per event identity.

The center is a bounded product history, not a second log store: entries are
the already-scrubbed event payloads, upserted by their opaque identity so a
recovery or dismissal rewrites the entry it resolves, and terminals only fall
under the age/count caps — an active issue stays discoverable until its owner
resolves or dismisses it.
"""

from __future__ import annotations

import json
import logging
import os
import time
from urllib.parse import quote, urlencode, urlparse

from waves.events import Lifecycle
from waves.redaction import scrub_event_text

logger = logging.getLogger("waves.diag")


class NotificationHistory:
    def __init__(self, path_file: str, *, max_entries: int = 200, max_age_days: int = 7) -> None:
        self._path = path_file
        self.max_entries = int(max_entries)
        self.max_age_days = int(max_age_days)
        self._entries: dict[str, dict] = {}
        self._savable = True

    @property
    def savable(self) -> bool:
        """False when an unreadable file could not be set aside; keep it, stop overwriting it."""
        return self._savable

    def load(self, *, now: float | None = None) -> None:
        """Replace memory with the stored history; an unreadable file is set aside, not overwritten."""
        self._entries.clear()
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            logger.debug("No notification history to load", exc_info=True)
            return
        except Exception:
            self._set_aside()
            return
        if not isinstance(data, list):
            self._set_aside()
            return
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                self._entries[item["id"]] = self._sanitize(item)
        self._prune(time.time() if now is None else float(now))

    def snapshot(self) -> str:
        return json.dumps(self.entries())

    def record(self, payload: dict, *, now: float | None = None) -> None:
        at = time.time() if now is None else float(now)
        entry = dict(payload)
        entry["details"] = list(payload.get("details") or [])
        entry["actions"] = list(payload.get("actions") or [])
        entry["references"] = dict(payload.get("references") or {})
        previous = self._entries.get(entry["id"])
        if previous is not None:
            entry["occurrences"] = max(int(previous.get("occurrences") or 1), int(entry.get("occurrences") or 1))
        entry["updated_at"] = at
        self._entries[entry["id"]] = entry
        self._prune(at)

    def entry(self, identity: str) -> dict | None:
        return self._entries.get(identity)

    def entries(self) -> list[dict]:
        return sorted(self._entries.values(), key=lambda item: item["updated_at"], reverse=True)

    def set_limits(self, *, max_entries: int, max_age_days: int, now: float | None = None) -> tuple[int, int]:
        self.max_entries = max(0, min(200, int(max_entries)))
        self.max_age_days = max(1, min(30, int(max_age_days)))
        self._prune(time.time() if now is None else float(now))
        return self.max_entries, self.max_age_days

    def clear(self) -> None:
        """Drop resolved/dismissed history; active issues stay until their owner ends them."""
        for identity, entry in tuple(self._entries.items()):
            if entry.get("lifecycle") != "active":
                del self._entries[identity]

    def finish_one(self, identity: str, lifecycle: Lifecycle, *, now: float | None = None) -> bool:
        """Dismiss or resolve one retained active entry; False when absent or terminal."""
        entry = self._entries.get(identity)
        if entry is None or entry.get("lifecycle") != "active":
            return False
        at = time.time() if now is None else float(now)
        self._finish(entry, lifecycle, at)
        self._prune(at)
        return True

    def finish_matching(
        self,
        *,
        domain: str,
        provider_id: str = "",
        job_id: int | None = None,
        identity: str = "",
        now: float | None = None,
    ) -> bool:
        """An owner resolved a scope: mark every matching active entry resolved.

        Mirrors the live action index's match, so a resolution arriving after a
        restart still lands on the retained entry whose owner state it closes.
        """
        at = time.time() if now is None else float(now)
        changed = False
        for entry in self._entries.values():
            if entry.get("lifecycle") != "active":
                continue
            refs = entry.get("references") or {}
            if identity and entry.get("id") != identity:
                continue
            if str(entry.get("domain") or "") != domain:
                continue
            if provider_id and str(refs.get("provider_id") or "") != provider_id:
                continue
            if job_id is not None and refs.get("job_id") != job_id:
                continue
            self._finish(entry, Lifecycle.RESOLVED, at)
            changed = True
        if changed:
            self._prune(at)
        return changed

    def _finish(self, entry: dict, lifecycle: Lifecycle, at: float) -> None:
        entry["lifecycle"] = lifecycle.value
        entry["actions"] = []
        entry["updated_at"] = at

    def _terminal(self) -> list[dict]:
        return [entry for entry in self._entries.values() if entry.get("lifecycle") != "active"]

    def _sanitize(self, entry: dict) -> dict:
        """Re-scrub stored text: the file on disk may predate the redactor's current rules."""
        safe = dict(entry)
        for key in ("title", "summary", "diagnostics"):
            if isinstance(safe.get(key), str):
                safe[key] = scrub_event_text(safe[key])
        safe["details"] = [scrub_event_text(str(value)) for value in safe.get("details") or []]
        safe["actions"] = [value for value in safe.get("actions") or [] if isinstance(value, str)]
        refs = safe.get("references")
        safe["references"] = (
            {key: scrub_event_text(str(value)) if isinstance(value, str) else value for key, value in refs.items()}
            if isinstance(refs, dict)
            else {}
        )
        if not isinstance(safe.get("occurrences"), int):
            safe["occurrences"] = 1
        if not isinstance(safe.get("updated_at"), (int, float)):
            safe["updated_at"] = time.time()
        return safe

    def _set_aside(self) -> None:
        kept = self._path + ".bak"
        if os.path.exists(kept):
            kept = f"{kept}-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(self._path, kept)
        except OSError:
            self._savable = False
            logger.warning("Notification history could not be read or set aside; this session will not save it")
            return
        logger.warning("Notification history could not be read; the file was set aside and history starts empty")

    def _prune(self, now: float) -> None:
        cutoff = now - self.max_age_days * 86400
        for entry in self._terminal():
            if entry["updated_at"] < cutoff:
                del self._entries[entry["id"]]
        newest_first = sorted(self._terminal(), key=lambda item: item["updated_at"], reverse=True)
        for entry in newest_first[self.max_entries :]:
            del self._entries[entry["id"]]


_DRAFT_BODY_CAP = 7000


def entry_copy_text(entry: dict) -> str:
    """One notification's redacted copy text, scrubbed again at the boundary."""
    values = [entry.get("title"), entry.get("summary"), *(entry.get("details") or []), entry.get("diagnostics")]
    return "\n".join(scrub_event_text(str(value)) for value in values if value).strip()


def compose_report(entry: dict, *, version: str, platform_name: str) -> tuple[str, str]:
    """A reviewable draft for the project's issue tracker: plain cause and details,
    the advanced trace last, every part re-scrubbed at composition."""
    summary = scrub_event_text(str(entry.get("summary") or ""))
    lines = [summary] if summary else []
    details = [scrub_event_text(str(value)) for value in entry.get("details") or []]
    if details:
        lines += ["", "Details:", *[f"- {value}" for value in details]]
    diagnostics = scrub_event_text(str(entry.get("diagnostics") or ""))
    if diagnostics:
        lines += ["", "Advanced diagnostics:", diagnostics]
    lines += ["", f"Waves {version} · {platform_name}"]
    title = scrub_event_text(f"[{entry.get('code') or 'event'}] {entry.get('title') or 'Waves event'}")
    return title, "\n".join(lines).strip()


def issue_draft_url(repository_url: str, title: str, body: str) -> str:
    """A prefilled new-issue URL; nothing leaves the machine until the user submits the page."""
    base = str(repository_url or "").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    trimmed = body if len(body) <= _DRAFT_BODY_CAP else body[:_DRAFT_BODY_CAP].rstrip() + "\n\n…(draft truncated)"
    return f"{base}/issues/new?{urlencode({'title': title, 'body': trimmed}, quote_via=quote)}"

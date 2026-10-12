"""Admission of separate Apple sessions to one account and storefront.

Account confirmation belongs to a particular session and runtime identity.
Only deliberate stop choices persist here; guest credentials stay with the guest.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit


class RuntimeKind(StrEnum):
    BUILT_IN = "built_in"
    MANAGED = "managed"
    USER_MANAGED = "user_managed"


@dataclass(frozen=True)
class RuntimeProfile:
    id: str
    kind: RuntimeKind
    protocol: str
    endpoint: str = ""
    artifact_digest: str = ""
    provenance: str = ""
    container: str = ""
    decrypt_port: int = 10020


def local_wrapper_endpoint(value: str) -> str:
    """Wrapper-v2's plaintext decryption transport permits loopback only."""
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.port is None
        or not 1024 <= parsed.port <= 65535
    ):
        raise ValueError("Use a loopback HTTP endpoint with an explicit unprivileged port")  # noqa: TRY003
    return f"http://127.0.0.1:{parsed.port}"


def wrapper_session_evidence(auth: dict, *, artifact_verified: bool | None, revision: str) -> SessionEvidence:
    """A display label is not a verified service account identifier."""
    from hashlib import sha256

    identifier = auth.get("account_id")
    account_id = sha256(identifier.encode()).hexdigest() if isinstance(identifier, str) and identifier else ""
    return SessionEvidence(
        auth.get("reachable"),
        auth.get("state") == "authenticated" if auth.get("state") in ("authenticated", "logged_out") else None,
        True if auth.get("reachable") and auth.get("state") in ("authenticated", "logged_out") else None,
        artifact_verified,
        account_id,
        str(auth.get("storefront") or ""),
        revision,
    )


@dataclass(frozen=True)
class AccountContext:
    account_id: str
    storefront: str
    credential_revision: str


@dataclass(frozen=True)
class SessionEvidence:
    reachable: bool | None = None
    authenticated: bool | None = None
    protocol_compatible: bool | None = None
    artifact_verified: bool | None = None
    account_id: str = ""
    storefront: str = ""
    session_revision: str = ""


class AppleRuntimeSessions:
    """Keep bounded runtime facts and invalidate account admission on changes."""

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self._lock = RLock()
        self._profiles: dict[str, RuntimeProfile] = {}
        self._sessions: dict[str, SessionEvidence] = {}
        self._confirmed: set[str] = set()
        self._account = AccountContext("", "", "")
        self._account_generation = 0
        self._generations: dict[str, int] = {}
        self._stopped: set[str] = set()
        self._state_valid = True
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            stopped = payload["stopped"]
            self._state_valid = isinstance(stopped, list) and all(isinstance(item, str) for item in stopped)
            if self._state_valid:
                self._stopped = set(stopped)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            # An unreadable stop record cannot authorize a background restart.
            self._state_valid = False

    @property
    def _state_path(self) -> Path:
        return self.runtime_dir / "runtime-choices.json"

    def is_stopped(self, runtime_id: str) -> bool:
        with self._lock:
            return not self._state_valid or runtime_id in self._stopped

    def stop(self, runtime_id: str) -> None:
        with self._lock:
            self._generations[runtime_id] = self._generations.get(runtime_id, 0) + 1
            self._stopped.add(runtime_id)
            self._confirmed.discard(runtime_id)
            self._save_choices()

    def resume(self, runtime_id: str) -> None:
        with self._lock:
            self._generations[runtime_id] = self._generations.get(runtime_id, 0) + 1
            self._stopped.discard(runtime_id)
            self._save_choices()
            self._state_valid = True
            self._sessions.pop(runtime_id, None)
            self._confirmed.discard(runtime_id)

    def _save_choices(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, filename = tempfile.mkstemp(dir=self.runtime_dir, prefix="runtime-choices.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"stopped": sorted(self._stopped)}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(filename, self._state_path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(filename)

    def configure(self, profile: RuntimeProfile) -> None:
        with self._lock:
            if self._profiles.get(profile.id) != profile:
                self._generations[profile.id] = self._generations.get(profile.id, 0) + 1
                self._sessions.pop(profile.id, None)
                self._confirmed.discard(profile.id)
            self._profiles[profile.id] = profile

    def set_account(self, account: AccountContext) -> None:
        with self._lock:
            if self._account != account:
                self._account_generation += 1
                self._confirmed.clear()
            self._account = account

    def observe(self, runtime_id: str, evidence: SessionEvidence) -> None:
        with self._lock:
            previous = self._sessions.get(runtime_id)
            if previous is not None and (
                previous.authenticated,
                previous.account_id,
                previous.storefront,
                previous.session_revision,
                previous.protocol_compatible,
                previous.artifact_verified,
            ) != (
                evidence.authenticated,
                evidence.account_id,
                evidence.storefront,
                evidence.session_revision,
                evidence.protocol_compatible,
                evidence.artifact_verified,
            ):
                self._generations[runtime_id] = self._generations.get(runtime_id, 0) + 1
                self._confirmed.discard(runtime_id)
            self._sessions[runtime_id] = evidence

    def revision(self, runtime_id: str) -> tuple[int, int]:
        with self._lock:
            return self._account_generation, self._generations.get(runtime_id, 0)

    def readiness(self, runtime_id: str) -> str:
        with self._lock:
            if self.is_stopped(runtime_id):
                return "stopped"
            session = self._sessions.get(runtime_id)
            if runtime_id not in self._profiles or session is None:
                return "unknown"
            if session.reachable is not True:
                return "unreachable" if session.reachable is False else "unknown"
            if session.protocol_compatible is not True or session.artifact_verified is not True:
                return (
                    "incompatible" if False in (session.protocol_compatible, session.artifact_verified) else "unknown"
                )
            if session.authenticated is not True:
                return "sign_in_required" if session.authenticated is False else "unknown"
            if (self._account.account_id and session.account_id and self._account.account_id != session.account_id) or (
                self._account.storefront and session.storefront and self._account.storefront != session.storefront
            ):
                return "account_mismatch"
            verified = bool(
                self._account.account_id
                and self._account.account_id == session.account_id
                and self._account.storefront
                and self._account.storefront == session.storefront
            )
            return "ready" if verified or runtime_id in self._confirmed else "confirmation_required"

    def confirm_account(self, runtime_id: str) -> bool:
        with self._lock:
            if self.readiness(runtime_id) not in ("ready", "confirmation_required"):
                return False
            self._confirmed.add(runtime_id)
            return True

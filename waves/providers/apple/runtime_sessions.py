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


class AdmissionState(StrEnum):
    STOPPED = "stopped"
    UNKNOWN = "unknown"
    UNREACHABLE = "unreachable"
    INCOMPATIBLE = "incompatible"
    SIGN_IN_REQUIRED = "sign_in_required"
    ACCOUNT_MISMATCH = "account_mismatch"
    CONFIRMATION_REQUIRED = "confirmation_required"
    READY = "ready"


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

    def __init__(self, runtime_dir: Path, *, load_choices: bool = True) -> None:
        self.runtime_dir = runtime_dir
        self._lock = RLock()
        self._profiles: dict[str, RuntimeProfile] = {}
        self._sessions: dict[str, SessionEvidence] = {}
        self._confirmed: set[str] = set()
        self._account = AccountContext("", "", "")
        self._account_generation = 0
        self._generations: dict[str, int] = {}
        self._stopped: set[str] = set()
        self._resumed: set[str] = set()
        self._default_stopped = True
        self._state_valid = False
        self._choices_restored = False
        self._restoring = False
        self._pending_choices: dict[str, bool] = {}
        if load_choices:
            self.restore_choices()

    def _load_choices(self) -> tuple[set[str], set[str], bool, bool]:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return set(), set(), False, True
        except (OSError, ValueError):
            # An unreadable stop record cannot authorize a background restart.
            return set(), set(), True, False
        if not isinstance(payload, dict):
            return set(), set(), True, False
        stopped = payload.get("stopped")
        resumed = payload.get("resumed", [])
        default_stopped = payload.get("default_stopped", False)
        valid = (
            isinstance(stopped, list)
            and all(isinstance(item, str) and item.strip() for item in stopped)
            and isinstance(resumed, list)
            and all(isinstance(item, str) and item.strip() for item in resumed)
            and isinstance(default_stopped, bool)
        )
        if not valid:
            return set(), set(), True, False
        return set(stopped), set(resumed), default_stopped, True

    @property
    def _state_path(self) -> Path:
        return self.runtime_dir / "runtime-choices.json"

    @property
    def choices_restored(self) -> bool:
        with self._lock:
            return self._choices_restored

    def restore_choices(self) -> None:
        """Restore once on a worker, merging any earlier explicit Stop/Resume.

        Until restoration and pending-choice persistence complete, all runtimes
        remain stopped. Corrupt state keeps a default deny rule; an explicit
        Resume authorizes only its selected resource. Failure permits a retry.
        """
        with self._lock:
            if self._choices_restored or self._restoring:
                return
            self._restoring = True
        try:
            stopped, resumed, default_stopped, valid = self._load_choices()
            with self._lock:
                changed = set(self._profiles) | set(self._pending_choices) | stopped | resumed
                for runtime_id, wants_stop in self._pending_choices.items():
                    if wants_stop:
                        stopped.add(runtime_id)
                        resumed.discard(runtime_id)
                    else:
                        stopped.discard(runtime_id)
                        if default_stopped:
                            resumed.add(runtime_id)
                if self._pending_choices:
                    self._save_choices(stopped=stopped, resumed=resumed, default_stopped=default_stopped)
                    valid = True
                self._stopped, self._resumed, self._default_stopped = stopped, resumed, default_stopped
                self._state_valid = valid
                self._pending_choices.clear()
                self._choices_restored = True
                for runtime_id in changed:
                    self.invalidate(runtime_id)
        finally:
            with self._lock:
                self._restoring = False

    def is_stopped(self, runtime_id: str) -> bool:
        with self._lock:
            if not self._choices_restored:
                return True
            return runtime_id in self._stopped or (
                (not self._state_valid or self._default_stopped) and runtime_id not in self._resumed
            )

    def request_stop(self, runtime_id: str) -> None:
        """Disconnect admission immediately; stop() persists this choice on a worker."""
        with self._lock:
            self._generations[runtime_id] = self._generations.get(runtime_id, 0) + 1
            self._stopped.add(runtime_id)
            self._resumed.discard(runtime_id)
            self._sessions.pop(runtime_id, None)
            self._confirmed.discard(runtime_id)
            if not self._choices_restored:
                self._pending_choices[runtime_id] = True

    def stop(self, runtime_id: str) -> None:
        with self._lock:
            self.request_stop(runtime_id)
            if not self._choices_restored:
                return
            self._save_choices()

    def resume(self, runtime_id: str) -> None:
        with self._lock:
            if not self._choices_restored:
                self._pending_choices[runtime_id] = False
                self.invalidate(runtime_id)
                return
            stopped = self._stopped - {runtime_id}
            resumed = set(self._resumed)
            default_stopped = self._default_stopped or not self._state_valid
            if default_stopped:
                resumed.add(runtime_id)
            self._save_choices(stopped=stopped, resumed=resumed, default_stopped=default_stopped)
            self._stopped, self._resumed, self._default_stopped = stopped, resumed, default_stopped
            self._state_valid = True
            self._generations[runtime_id] = self._generations.get(runtime_id, 0) + 1
            self._sessions.pop(runtime_id, None)
            self._confirmed.discard(runtime_id)

    def _save_choices(
        self,
        *,
        stopped: set[str] | None = None,
        resumed: set[str] | None = None,
        default_stopped: bool | None = None,
    ) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, filename = tempfile.mkstemp(dir=self.runtime_dir, prefix="runtime-choices.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "stopped": sorted(self._stopped if stopped is None else stopped),
                        "resumed": sorted(self._resumed if resumed is None else resumed),
                        "default_stopped": self._default_stopped if default_stopped is None else default_stopped,
                    },
                    stream,
                )
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
                # First observation cannot revoke a prior admitted account.
                # invalidate_account already revoked any preceding context.
                first_context = self._account == AccountContext("", "", "") and not self._confirmed
                if not first_context:
                    self._account_generation += 1
                self._confirmed.clear()
            self._account = account

    def invalidate(self, runtime_id: str) -> None:
        """Revoke this resource's evidence and confirmation without disk access."""
        with self._lock:
            self._generations[runtime_id] = self._generations.get(runtime_id, 0) + 1
            self._sessions.pop(runtime_id, None)
            self._confirmed.discard(runtime_id)

    def invalidate_account(self) -> None:
        """Revoke all account evidence synchronously before credential changes."""
        with self._lock:
            self._account_generation += 1
            self._account = AccountContext("", "", "")
            self._sessions.clear()
            self._confirmed.clear()

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

    def readiness(self, runtime_id: str) -> AdmissionState:
        with self._lock:
            if self.is_stopped(runtime_id):
                return AdmissionState.STOPPED
            session = self._sessions.get(runtime_id)
            if runtime_id not in self._profiles or session is None:
                return AdmissionState.UNKNOWN
            if session.reachable is not True:
                return AdmissionState.UNREACHABLE if session.reachable is False else AdmissionState.UNKNOWN
            if session.protocol_compatible is not True or session.artifact_verified is not True:
                return (
                    AdmissionState.INCOMPATIBLE
                    if False in (session.protocol_compatible, session.artifact_verified)
                    else AdmissionState.UNKNOWN
                )
            if session.authenticated is not True:
                return AdmissionState.SIGN_IN_REQUIRED if session.authenticated is False else AdmissionState.UNKNOWN
            if (self._account.account_id and session.account_id and self._account.account_id != session.account_id) or (
                self._account.storefront and session.storefront and self._account.storefront != session.storefront
            ):
                return AdmissionState.ACCOUNT_MISMATCH
            verified = bool(
                self._account.account_id
                and self._account.account_id == session.account_id
                and self._account.storefront
                and self._account.storefront == session.storefront
            )
            return (
                AdmissionState.READY
                if verified or runtime_id in self._confirmed
                else AdmissionState.CONFIRMATION_REQUIRED
            )

    def confirm_account(self, runtime_id: str) -> bool:
        with self._lock:
            if self.readiness(runtime_id) not in (AdmissionState.READY, AdmissionState.CONFIRMATION_REQUIRED):
                return False
            self._confirmed.add(runtime_id)
            return True

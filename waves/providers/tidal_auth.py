"""Detached TIDAL validation and a guarded, short credential commit.

The provider owns attempt/epoch ordering through ``commit_if_current``. No SDK
request or file flush runs in that callback, and a stale attempt never acquires
the live session or changes its saved sign-in.
"""

from __future__ import annotations

import contextlib
import datetime
import os
from collections.abc import Callable
from dataclasses import replace
from threading import Event
from urllib.parse import urlsplit

import tidalapi

from waves.config import Tidal, harden_api_session, session_quality_from_word
from waves.model.cfg import Token

type CommitIfCurrent = Callable[[Callable[[], None]], bool]


def _answered_status(exc: BaseException) -> int | None:
    # Same refusal policy as WavesTidal, including tidalapi's translated or
    # malformed error bodies whose HTTP status survives only in the chain.
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(getattr(current, "response", None), "status_code", None)
        if isinstance(status, int):
            return status
        current = current.__cause__ or current.__context__
    return None


def _expiry_epoch(value: datetime.datetime | float | None) -> float:
    # Match dataclasses_json's datetime encoding used by token_persist, while
    # retaining the epoch float that load_oauth_session round-trips unchanged.
    return value.timestamp() if isinstance(value, datetime.datetime) else value or 0.0


class TidalLoginAttempt:
    """One worker's isolated login, published only by its provider's guard."""

    def __init__(
        self,
        owner: Tidal,
        *,
        resume: bool = False,
        register_secrets: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        self._owner = owner
        self._resume = resume
        self._saved = replace(owner.data)
        self._had_saved = owner.token_from_storage
        self._is_pkce = getattr(owner, "is_pkce", True) if resume else True
        self._sign_in_at_stake = getattr(owner, "_sign_in_at_stake", True)
        self._register_secrets = register_secrets
        self._discarded = Event()
        self._validated = False
        self._refused = False
        self._adopted = False
        self._staged: str | None = None
        self._pending: Token | None = None

        # Construct only the SDK session: Tidal/WavesTidal constructors are
        # process singletons and would return the live credential owner.
        config = tidalapi.Config(item_limit=10000)
        config.client_id = owner.original_client_id
        config.client_secret = owner.original_client_secret
        config.client_id_pkce = owner.original_client_id_pkce
        config.client_secret_pkce = owner.original_client_secret_pkce
        self._candidate = tidalapi.Session(config)
        harden_api_session(self._candidate)
        settings = getattr(owner, "settings", None)
        quality = session_quality_from_word(settings.data.tidal_quality_audio) if settings is not None else None
        if quality is not None:
            self._candidate.audio_quality = quality
        elif getattr(owner, "session", None) is not None:
            self._candidate.audio_quality = owner.session.audio_quality
        self._candidate.video_quality = tidalapi.VideoQuality.high

    def begin(self) -> str:
        if self._resume or self._discarded.is_set():
            return ""
        return self._candidate.pkce_login_url()

    def _note_secrets(self, facts: dict[str, str]) -> None:
        if self._register_secrets is not None:
            with contextlib.suppress(Exception):
                self._register_secrets(facts)

    def _note_candidate_secrets(self) -> None:
        session = self._candidate
        facts = {key: str(getattr(session, key, "") or "") for key in ("access_token", "refresh_token", "session_id")}
        facts["account_id"] = str(getattr(session.user, "id", "") or "")
        facts["username"] = str(getattr(session.user, "username", "") or "")
        self._note_secrets(facts)

    def _load_saved(self) -> bool:
        saved = self._saved
        if not self._had_saved or not saved.token_type or not saved.access_token:
            return False
        self._note_secrets({"access_token": saved.access_token, "refresh_token": saved.refresh_token or ""})
        loaded = self._candidate.load_oauth_session(
            saved.token_type,
            saved.access_token,
            saved.refresh_token,
            saved.expiry_time,  # ty: ignore[invalid-argument-type]  # tidalapi round-trips the saved epoch float
            is_pkce=self._is_pkce,
        )
        self._note_candidate_secrets()
        return loaded

    def validate(self, payload: str) -> bool:
        """Exchange and validate on this worker without changing the owner."""
        if self._discarded.is_set() or self._validated or self._adopted:
            return False
        self._refused = False
        try:
            if self._resume:
                if not self._load_saved() or self._discarded.is_set():
                    return False
            else:
                payload = payload.strip()
                redirect = urlsplit(payload)
                if redirect.scheme != "https" or not redirect.netloc:
                    return False
                token = self._candidate.pkce_get_auth_token(payload)
                # process_auth_token performs SDK requests; teach the sink the
                # exchange's secrets before any such request can fail or log.
                self._note_secrets(
                    {
                        key: value
                        for key, value in token.items()
                        if key in {"access_token", "refresh_token"} and isinstance(value, str)
                    }
                )
                if self._discarded.is_set():
                    return False
                self._candidate.process_auth_token(token, is_pkce_token=True)
                self._note_candidate_secrets()
            if self._discarded.is_set() or not self._candidate.check_login():
                return False
            candidate = self._candidate
            if not candidate.token_type or not candidate.access_token:
                return False
            self._pending = Token(
                token_type=candidate.token_type,
                access_token=candidate.access_token,
                refresh_token=candidate.refresh_token,
                expiry_time=_expiry_epoch(candidate.expiry_time),
            )
            self._validated = not self._discarded.is_set()
        except Exception as exc:
            # No exception text: SDK errors can contain the redirect or token.
            self._refused = self._resume and self._sign_in_at_stake and _answered_status(exc) in {401, 403}
            return False
        else:
            return self._validated

    def _writable(self) -> bool:
        return not (
            self._discarded.is_set()
            or getattr(self._owner, "persistence_frozen", False)
            or self._owner._keep_file_untouched
        )

    def persist(self, commit_if_current: CommitIfCurrent) -> bool:
        """Flush privately, then publish and adopt within the provider guard."""
        pending = self._pending
        if pending is None or not self._validated or self._adopted or not self._writable():
            return False
        committed = False
        try:
            self._staged = self._owner.stage_serialized(pending.to_json())
            if not self._writable():
                return False
            staged = self._staged

            def commit() -> None:
                nonlocal committed
                if not self._writable():
                    return
                if self._resume and self._owner.data != self._saved:
                    return
                # One atomic replace, never the Windows retry/sleep loop. A
                # refused replacement leaves both live owner and old file intact.
                os.replace(staged, self._owner.file_path)
                self._staged = None
                self._owner.session = self._candidate
                self._owner.data = pending
                self._owner.original_client_id = self._candidate.config.client_id
                self._owner.original_client_secret = self._candidate.config.client_secret
                self._owner.original_client_id_pkce = self._candidate.config.client_id_pkce
                self._owner.original_client_secret_pkce = self._candidate.config.client_secret_pkce
                self._owner.is_pkce = self._is_pkce
                self._owner.is_atmos_session = False
                self._owner.token_from_storage = True
                self._adopted = committed = True

            # A manifest worker may still be restoring its Atmos client on
            # the owner. Wait for that worker before entering the authority
            # guard; cancellation never has to wait for this engine lock.
            stream_lock = getattr(self._owner, "stream_lock", None)
            with stream_lock if stream_lock is not None else contextlib.nullcontext():
                allowed = commit_if_current(commit)
            if committed:
                # The legacy no-argument listener reads the adopted session;
                # invoke it only after the guard has released its lock.
                self._owner._note_session_credentials()
        except Exception:
            return False
        else:
            return allowed and committed
        finally:
            self._remove_staged()

    def reject(self, commit_if_current: CommitIfCurrent) -> bool:
        """Delete only this positively refused, still-current saved sign-in."""
        if not self._refused or not self._writable():
            return False
        rejected = False

        def commit() -> None:
            nonlocal rejected
            owner = self._owner
            if not self._writable() or owner.data != self._saved or not getattr(owner, "_sign_in_at_stake", True):
                return
            with contextlib.suppress(FileNotFoundError):
                os.remove(owner.file_path)
            owner.token_from_storage = False
            rejected = True

        try:
            return commit_if_current(commit) and rejected
        except Exception:
            return False

    def _remove_staged(self) -> None:
        staged = self._staged
        if staged is not None:
            with contextlib.suppress(OSError):
                os.remove(staged)
            self._staged = None

    def discard(self) -> None:
        """Invalidate this attempt and remove its private staging, if present."""
        self._discarded.set()
        self._remove_staged()

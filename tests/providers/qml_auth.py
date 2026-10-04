"""Detached provider auth candidates for the offscreen sign-in scenarios."""

from __future__ import annotations

from collections.abc import Callable


class CallbackLoginAttempt:
    """Fake the account service while retaining the bridge's commit fence."""

    def __init__(
        self,
        begin: Callable[[], str],
        validate: Callable[[str], bool],
        persist: Callable[[], None] | None = None,
    ) -> None:
        self._begin = begin
        self._validate = validate
        self._persist = persist or (lambda: None)
        self.discarded = False

    def begin(self) -> str:
        return self._begin()

    def validate(self, payload: str) -> bool:
        return self._validate(payload)

    def persist(self, commit_if_current: Callable[[Callable[[], None]], bool]) -> bool:
        return commit_if_current(self._persist)

    def reject(self, commit_if_current: Callable[[Callable[[], None]], bool]) -> bool:
        return commit_if_current(lambda: None)

    def discard(self) -> None:
        self.discarded = True

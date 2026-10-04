"""A mis-pasted sign-in field must never reach the logs.

The sign-in flow asks the user to copy a URL from the browser, so a stale
clipboard entry (a password, a chat message, a personal note) is a realistic
slip. The compatibility slot refuses a stray paste before scheduling account
work. An accepted URL reaches a detached candidate, whose exceptions may
contain that full URL: auth orchestration must log only a generic failure.
"""

from __future__ import annotations

import logging

from conftest import _InlinePool, _Signal
from providers.fakes import BareProvider
from providers.qml_auth import CallbackLoginAttempt

from waves.desktop.backend import WavesBridge
from waves.desktop.providers.auth import apply_login_event, start_login
from waves.providers.base import ProviderDescriptor


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(self.format(record) + (record.exc_text or ""))


class _Stub:
    completeLogin = WavesBridge.completeLogin

    def __init__(self):
        self.statuses: list[str] = []
        self.busy: list[bool] = []
        # Booby-trapped on purpose: a paste that fails the guard must never
        # reach tidalapi or the pool at all.
        self.tidal = None
        self.threadpool = None

    def _set_status(self, text):
        self.statuses.append(text)

    def _set_busy(self, on):
        self.busy.append(bool(on))


class _LoginEventSignal(_Signal):
    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge

    def emit(self, event) -> None:
        super().emit(event)
        apply_login_event(self.bridge, event)


class _PasteProvider(BareProvider):
    id = "tidal"

    def __init__(self):
        self.payloads: list[str] = []

    @staticmethod
    def descriptor() -> ProviderDescriptor:
        return ProviderDescriptor(id="tidal", name="Fixture TIDAL")

    def _validate(self, payload: str) -> bool:
        self.payloads.append(payload)
        raise KeyError(payload)

    def create_login_attempt(self, *, resume=False, register_secrets=None):
        return CallbackLoginAttempt(lambda: "https://tidal.test/authorize", self._validate)


class _StagedStub(_Stub):
    def __init__(self):
        super().__init__()
        self.provider = _PasteProvider()
        self.providers = {"tidal": self.provider}
        self.threadpool = _InlinePool()
        self._providerLoginEvent = _LoginEventSignal(self)
        self.providerLoginUrlReady = _Signal()
        self.loginUrlReady = _Signal()
        self.providerLoginFinished = _Signal()

    def _set_login_busy(self, provider_id: str, value: bool) -> None:
        self._set_busy(value)


def _watching_waves_logger():
    handler = _Capture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("waves")
    logger.addHandler(handler)
    return logger, handler


def test_a_stray_clipboard_paste_is_refused_and_never_logged():
    logger, handler = _watching_waves_logger()
    try:
        stub = _Stub()
        stub.completeLogin("hunter2 remind mom about tuesday")

        assert stub.statuses and "Copy the full URL" in stub.statuses[-1]
        assert stub.busy == [], "a refused paste must not cycle the spinner"
        joined = "\n".join(handler.messages)
        assert "hunter2" not in joined and "tuesday" not in joined
    finally:
        logger.removeHandler(handler)


def test_a_signin_url_reaches_the_candidate_without_logging_its_exception():
    logger, handler = _watching_waves_logger()
    try:
        stub = _StagedStub()
        start_login(stub, "tidal")
        stub.busy.clear()
        paste = "https://tidal.com/android/login/auth?code=private-one-time-code"

        stub.completeLogin(paste)

        assert stub.provider.payloads == [paste]
        assert stub.statuses[-1] == "Sign-in failed. Try again."
        assert stub.busy == [True, False]
        assert stub.providerLoginFinished.emits == [("tidal", False)]
        joined = "\n".join(handler.messages)
        assert "Provider sign-in failed" in joined
        assert paste not in joined and "private-one-time-code" not in joined
    finally:
        logger.removeHandler(handler)

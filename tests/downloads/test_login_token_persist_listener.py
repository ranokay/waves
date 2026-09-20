"""How the redactor hears about session credentials.

Persisting a token and refreshing one both report through the listener, a
missing or failing listener stays harmless, and the desktop bridge registers
itself as that listener.
"""

from __future__ import annotations


def test_a_token_persist_tells_the_listener():
    # The event carries no session object (the UI collects the credential
    # facts through its provider); it only says "now".
    from waves.config import Tidal

    tidal = Tidal.__new__(Tidal)
    seen: list[str] = []
    tidal.on_session_credentials = lambda: seen.append("noted")

    tidal._note_session_credentials()

    assert seen == ["noted"]


def test_no_listener_is_not_an_error():
    from waves.config import Tidal

    tidal = Tidal.__new__(Tidal)
    tidal.on_session_credentials = None
    tidal.session = object()

    tidal._note_session_credentials()  # a headless run installs nothing


def test_a_listener_that_raises_never_takes_the_login_down():
    from waves.config import Tidal

    tidal = Tidal.__new__(Tidal)

    def boom(session):
        raise RuntimeError("the redactor is unhappy")

    tidal.on_session_credentials = boom
    tidal.session = object()

    tidal._note_session_credentials()


def test_the_refresh_and_the_persist_both_report():
    """Structural: an Atmos switch forces a refresh that is deliberately NOT
    persisted, so the persist call alone would miss every one of them."""
    import inspect

    from waves.config import Tidal

    assert "_note_session_credentials()" in inspect.getsource(Tidal.token_persist)
    assert "_note_session_credentials()" in inspect.getsource(Tidal._reauthenticate_current_client)


def test_the_bridge_installs_itself_as_the_listener():
    import inspect

    from waves.desktop.backend import WavesBridge

    source = inspect.getsource(WavesBridge.__init__)

    assert "on_session_credentials = self._register_session_secrets" in source


def test_the_registrar_pulls_the_facts_through_the_provider():
    """The registrar takes no session argument at all: the credential facts
    come from the provider, and both the login path and the config layer's
    credential event call it the same no-arg way."""
    import inspect

    from waves.desktop.backend import WavesBridge

    assert list(inspect.signature(WavesBridge._register_session_secrets).parameters) == ["self"]

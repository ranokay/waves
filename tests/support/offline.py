"""Keep offscreen Main.qml scenarios off the live TIDAL API.

Every scenario that builds ``WavesBridge(tidal=None)`` gets a REAL
cached-token login fired from the bridge's ``__init__``: a network round
trip whose completion flips ``sessionResolved`` and raises the first-run
welcome gate, a full-window surface with a click-eating MouseArea. When
that lands mid-scenario it silently swallows every later synthetic click
or hover, so whether a test passed depended on live TIDAL latency (the
source of a family of full-suite-only failures). A unit test must not
talk to the live API at all, so:

- call :func:`patch_offline` BEFORE constructing the bridge (the login
  fires from ``__init__``; a later patch loses the race), and
- run ``PARK_LOGIN_QML`` through the scenario's ``q()`` helper right
  after the boot handover, unless the scenario is actually about the
  welcome surface or a sign-in.
"""

from __future__ import annotations


def patch_offline() -> None:
    """Make the bridge's cached-token login resolve instantly, offline."""
    from waves.waves_ui.session import WavesTidal

    WavesTidal.login_token = lambda self: False  # type: ignore[method-assign]


# The session resolves logged-out (instantly, via patch_offline), so the
# first-run welcome gate is up and would swallow every synthetic click and
# hover. Scenarios that test other surfaces park it and put the welcome
# back on its provider cards, so a sign-in surface left by another step can
# never linger. Scenarios actually about onboarding or sign-in keep this
# state away (see tests/ui/test_onboarding_state_qml.py).
PARK_LOGIN_QML = "setupMode = 'cards'; setupUrlOpened = false; providerPicker.visible = false"

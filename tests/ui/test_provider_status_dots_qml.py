"""Issue #223: per-provider header lights, Browse availability, no header sign-out.

WHAT THIS FENCES OFF
--------------------
1. The TIDAL-only "OFFLINE" pill and the header's SIGN OUT. The header shows
   one compact status dot per provider the bridge reports; sign-out lives on
   the TIDAL card in Settings (its own journey test owns the click). No word
   in the header can contradict a provider that is usable.

2. Browse as a fixed tab. The destination exists while a configured provider
   declares Browse and is hidden when none does; signed out it keeps the
   sign-in call to action (#220), signed in it is unchanged. A stub whose
   providers cannot fill Browse proves the hidden state through the bridge
   answer, not a QML branch.

3. The dots as TIDAL/Apple hardcode. A third provider registered after the
   header was written renders its own dot, with its own live state, through
   the descriptor contract alone -- the paper test, on the header.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js

from waves.providers import Capability
from waves.providers.base import ProviderDescriptor, StatusKind


def _q(text: str) -> str:
    return json.dumps(text)


def _visible_text(scope: str, text: str) -> str:
    """Whether a VISIBLE Text with this exact string exists under the scope."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.visible === true"
        f" && o.text !== undefined && String(o.text) === {_q(text)}; }});\n"
        "  return hit !== null;\n"
    )


def _any_text(scope: str, text: str) -> str:
    """Whether any Text with this exact string exists under the scope."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.text !== undefined"
        f" && String(o.text) === {_q(text)}; }});\n"
        "  return hit !== null;\n"
    )


def _light_probe(provider_id: str) -> str:
    """The rendered state of one provider's header light."""
    return scene_js(
        f"  var light = findObject(root, 'providerLight_' + {_q(provider_id)});\n"
        "  if (!light) return null;\n"
        "  var dot = findObject(root, 'providerLightDot_' + light.providerId);\n"
        "  return JSON.stringify({\n"
        "    state: String(light.lightState), word: String(light.statusName),\n"
        "    color: dot ? String(dot.color) : '',\n"
        "    visible: light.visible === true && light.width > 0 });\n"
    )


def _nav_visible(label: str) -> str:
    """Whether the NavTab carrying this label is itself visible."""
    return scene_js(
        "  var hit = findFirst(root, function (o) { return o.label !== undefined"
        f" && String(o.label) === {_q(label)}; }});\n"
        "  return hit !== null && hit.visible === true;\n"
    )


@pytest.mark.qml
def test_the_header_reports_each_provider_and_browse_hides_without_one():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-provider-lights-",
        failure_message="the per-provider header lights or Browse availability regressed",
        drop=("waves.qt",),
    )


class _NewCo:
    """A provider registered after every QML surface was written."""

    id = "newco"
    name = "NewCo"
    is_logged_in = True

    @staticmethod
    def descriptor() -> ProviderDescriptor:
        return ProviderDescriptor(id="newco", name="NewCo", status_kind=StatusKind.SESSION)


def _settle_until(q, settle, expr: str, want, tries: int = 20) -> bool:
    for _ in range(tries):
        if q(expr) == want:
            return True
        settle(80)
    return False


def _light_state_expr(provider_id: str) -> str:
    return (
        "String((root.providerLights.filter(function (l) {"
        f" return String(l.id) === {_q(provider_id)}; }})[0] || {{}}).state || '')"
    )


def _run_scenario() -> int:  # noqa: C901 (one straight scenario)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    failures: list[str] = []

    # A fresh answered profile: TIDAL signed out, Apple off, gates parked.
    q("setupSettings.firstRunAnswered = true; setupSettings.setupChipDismissed = true")
    q("root.setupMode = 'cards'; root.setupUrlOpened = false; providerPicker.visible = false")
    q('waves.applySettings({"apple_enabled": false})')
    bridge._session_resolved = True
    bridge.sessionResolvedChanged.emit()
    q("scrollDressing.visible = false")
    settle(300)

    # 1. The old pill is gone: no OFFLINE/CONNECTED word and no header
    #    sign-out; the TIDAL card in Settings owns the action now (covered by
    #    the reachability scenario).
    if q(_visible_text("headerRow", "OFFLINE")) or q(_any_text("headerRow", "CONNECTED")):
        failures.append("the header still carries the TIDAL-only connection pill")
    if q(_visible_text("headerRow", "SIGN OUT")):
        failures.append("the header still carries SIGN OUT")

    # 2. One dot for the one provider that has a status: TIDAL, signed out.
    if not _settle_until(q, settle, "root.providerLights.length", 1):
        failures.append(f"the header did not report the TIDAL light: {q('root.providerLights.length')}")
    else:
        if q(_light_state_expr("tidal")) != "signed_out":
            failures.append(f"TIDAL's light does not read signed out: {q(_light_state_expr('tidal'))}")
        probe = q(_light_probe("tidal"))
        if probe is None:
            failures.append("the TIDAL dot did not render")
        else:
            state = json.loads(probe)
            if state["word"] != "TIDAL: Signed out":
                failures.append(f"the TIDAL dot's status word is wrong: {state['word']}")
            if state["color"] != "#ffb01f":
                failures.append(f"a signed-out session is not gold: {state['color']}")
            if not state["visible"]:
                failures.append("the TIDAL dot is not visible")

    # 3. Apple on: the header reflects BOTH providers; no word anywhere in the
    #    header says the app is offline while Apple's search is usable.
    bridge.settings.data.apple_enabled = True
    bridge.appleStatusChanged.emit()
    if not _settle_until(q, settle, "root.providerLights.length", 2):
        failures.append(f"Apple's light did not join the header: {q('root.providerLights.length')}")
    else:
        apple = q(_light_probe("apple"))
        if apple is None:
            failures.append("the Apple dot did not render")
        else:
            state = json.loads(apple)
            # The host may already carry a managed runtime or cookies export;
            # the light must carry the bridge's own live setup word, whatever
            # this machine's state is.
            apple_status = bridge.appleStatus()
            if state["state"] != apple_status["state"]:
                failures.append(f"Apple's light disagrees with appleStatus(): {apple}")
            if state["word"] != f"Apple Music: {apple_status['word']}":
                failures.append(f"Apple's light does not carry its setup word: {apple}")
            if state["color"] not in ("#3dff6e", "#ffb01f", "#ff5a52", "#6b6f78"):
                failures.append(f"Apple's dot colour is outside the status vocabulary: {state['color']}")
    if q(_visible_text("headerRow", "OFFLINE")):
        failures.append("the header reads OFFLINE while Apple search is usable")

    # Browse, signed out: the destination exists with its sign-in call to
    # action (issue #220's shape), not a blank pane.
    if not q(_nav_visible("Browse")):
        failures.append("the Browse tab vanished while TIDAL can fill it")
    q("root.openBrowse()")
    settle(300)
    q("scrollDressing.visible = false")
    settle(120)
    if not q(_visible_text("browseLanding", "Sign in to TIDAL")):
        failures.append("the signed-out Browse pane lost its sign-in call to action")

    # 4. TIDAL signed in: the light flips green/Connected and Browse stays
    #    exactly as it was (no call to action).
    bridge._set_logged_in(True)
    if not _settle_until(q, settle, _light_state_expr("tidal"), "signed_in"):
        failures.append("the TIDAL light did not flip when the session signed in")
    else:
        probe = json.loads(q(_light_probe("tidal")) or "{}")
        if probe.get("color") != "#3dff6e":
            failures.append(f"a signed-in session is not green: {probe}")
        if probe.get("word") != "TIDAL: Connected":
            failures.append(f"a signed-in session does not read Connected: {probe}")
    if q(_visible_text("browseLanding", "Sign in to TIDAL")):
        failures.append("the Browse call to action outlived the sign-in")
    if not q(_nav_visible("Browse")):
        failures.append("the Browse tab vanished while signed in")

    # 5. The paper test: a third provider registered after the fact renders
    #    its own dot, with its own live state, with zero QML edits.
    bridge.providers["newco"] = _NewCo()
    q("root.refreshProviderLights()")
    settle(200)
    probe = q(_light_probe("newco"))
    if probe is None:
        failures.append("a third provider did not render a header dot")
    else:
        state = json.loads(probe)
        if state["state"] != "signed_in" or state["word"] != "NewCo: Connected":
            failures.append(f"the third provider's dot does not carry its live state: {probe}")

    # 6. No configured provider declares Browse (the capability is the whole
    #    rule): the destination is hidden and a programmatic open falls
    #    through to Search instead of a dead pane.
    tidal = bridge.providers["tidal"]
    tidal.capabilities = frozenset(c for c in tidal.capabilities if c is not Capability.BROWSE)
    q("root.refreshBrowseNav()")
    settle(200)
    if q("root.browseAvailable"):
        failures.append("Browse stayed available with no browse-capable provider")
    if q(_nav_visible("Browse")):
        failures.append("the Browse tab stayed visible with no browse-capable provider")
    q("root.openBrowse()")
    settle(250)
    if bool(q("root.browseOpen")) or q("root.navOrigin") != "search":
        failures.append("opening an unavailable Browse did not fall through to Search")
    if not q(_nav_visible("Search")):
        failures.append("Search is not the active tab after Browse went away")
    if bool(q("waves.browseNav().available")):
        failures.append("the bridge still reports Browse available without a browse provider")

    for line in failures:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())

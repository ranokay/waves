"""Every ``waves.<name>`` the QML calls really is reachable from QML.

A Python method on the bridge is only visible to QML when it carries a
``@Slot`` decorator: without one it never reaches ``staticMetaObject``, the
context property has no such member, and the call throws a TypeError at the
moment the user triggers it. Nothing catches that at import time, and a unit
test that binds the unbound function onto a plain stub (which is how the
bridge tests are written, see tests/conftest.py) passes either way, so a whole
feature can be inert with a green suite: the throw happens only when the user
triggers the call.

This is the gate for it. It reads the QML, collects every ``waves.NAME``
reference, and asserts each one is a real member of the bridge's meta object.
"""

from __future__ import annotations

import ast
import re

from support.paths import QML_DIR, REPO_ROOT

from waves.desktop.backend import WavesBridge

_REFERENCE = re.compile(r"\bwaves\.([A-Za-z_]\w*)")


def _code_only(source: str) -> str:
    """``source`` with its comments and string bodies blanked out.

    Both matter. A prose comment in Main.qml mentions ``waves.json`` (the
    settings file, not a bridge member), which a naive regex reads as a missing
    slot; and a URL inside a string carries a ``//`` that a line-based comment
    strip would mistake for the start of a comment, swallowing whatever real
    code followed it on that line. Walking the characters once handles both.
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            while i < n and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
            i += 1
            out.append('""')
            continue
        if ch == "/" and i + 1 < n:
            if source[i + 1] == "/":
                while i < n and source[i] != "\n":
                    i += 1
                continue
            if source[i + 1] == "*":
                end = source.find("*/", i + 2)
                i = n if end < 0 else end + 2
                out.append(" ")
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _bridge_members() -> set[str]:
    """Every name QML can resolve on the bridge: invokable methods and signals
    from the meta object, plus its properties.

    Methods and properties are read differently on purpose. A method name comes
    back as a QByteArray, which decodes; a property name comes back as ``str``
    already, and calling ``bytes()`` on it raises.
    """
    mo = WavesBridge.staticMetaObject
    names = {bytes(mo.method(i).name()).decode() for i in range(mo.methodCount())}
    names |= {str(mo.property(i).name()) for i in range(mo.propertyCount())}
    return names


def test_every_qml_call_into_the_bridge_resolves():
    members = _bridge_members()
    missing: dict[str, set[str]] = {}
    for qml in sorted(QML_DIR.rglob("*.qml")):
        used = set(_REFERENCE.findall(_code_only(qml.read_text(encoding="utf-8"))))
        absent = used - members
        if absent:
            missing[qml.name] = absent
    assert not missing, f"QML calls bridge members that QML cannot see (missing @Slot or @Property): {missing!r}"


def test_the_hover_prefetch_slots_are_the_ones_that_regressed():
    """The three hover-warm entry points, pinned by name.

    The general gate above only fires while the QML still calls them. These
    stay red even if a refactor drops the call site, because the decorator
    going missing is the defect, not the call.
    """
    members = _bridge_members()
    for name in ("prefetchArtist", "prefetchAlbumTracks", "prefetchBrowseItem"):
        assert name in members, f"{name} is not reachable from QML"


def _declared_public_signals() -> set[str]:
    """Public ``Signal`` names declared on public bridge classes.

    Read from source, not the meta object: the meta object also carries
    Qt's own signals (``objectNameChanged``) and inherited thread-hop
    relays. Only public classes count -- ``_ProgressSignals`` is a
    per-download thread relay whose members are internal by construction,
    the same category BRIDGE.md's internal-signals section exempts.
    """
    names = set()
    for path in (REPO_ROOT / "waves/desktop/backend.py", REPO_ROOT / "waves/desktop/bridge_library.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                continue
            for item in node.body:
                if not isinstance(item, ast.Assign):
                    continue
                if not (
                    isinstance(item.value, ast.Call)
                    and isinstance(item.value.func, ast.Name)
                    and item.value.func.id == "Signal"
                ):
                    continue
                for target in item.targets:
                    if isinstance(target, ast.Name) and not target.id.startswith("_"):
                        names.add(target.id)
    return names


def test_every_public_signal_appears_in_the_contract_doc():
    """BRIDGE.md is the seam map the bridge split reads: a public signal with
    no row leaves the next extraction guessing at its contract. Deleting one
    row fails this; so does declaring a new public signal without one.

    Rows only, not prose: several signals are also named in the surrounding
    text, and a row deleted while its prose mention survives must still fail.
    """
    lines = (REPO_ROOT / "waves/desktop/BRIDGE.md").read_text(encoding="utf-8").splitlines()
    rows = "\n".join(line for line in lines if line.startswith("|"))
    missing = [
        name
        for name in sorted(_declared_public_signals())
        if not re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", rows)
    ]
    assert not missing, f"public bridge signals missing from BRIDGE.md: {missing!r}"

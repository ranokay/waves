"""Every plain-urllib read carries the certifi-backed context.

A bare ``urlopen`` trusts the linked OpenSSL's built-in CA path, which in a
packaged macOS build is the build machine's Homebrew folder: on a Mac
without it the MusicBrainz read failed verification. This context loads only
the certifi bundle that ships inside the app, so a read verifies the same way
on every machine regardless of OpenSSL's layout.
"""

from __future__ import annotations

import ast
import ssl
from pathlib import Path

import certifi

from waves.tls import tls_context

_ROOT = Path(__file__).resolve().parent.parent
_PKG = _ROOT / "waves"


def _urlopen_calls() -> list[tuple[Path, ast.Call]]:
    """Every call in the shipped sources that invokes urllib's urlopen,
    including calls through a ``from urllib.request import urlopen as x``
    alias. The frozen build compiles the root launcher as its entry point, so
    it is scanned beside the package."""
    sources = sorted(_PKG.rglob("*.py"))
    if (_ROOT / "waves.py").is_file():
        sources.append(_ROOT / "waves.py")
    calls = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = {"urlopen"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "urllib.request":
                aliases.update(alias.asname for alias in node.names if alias.name == "urlopen" and alias.asname)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            matched = fn.attr == "urlopen" if isinstance(fn, ast.Attribute) else getattr(fn, "id", "") in aliases
            if matched:
                calls.append((path, node))
    return calls


def _passes_shared_context(call: ast.Call) -> bool:
    """The call supplies ``context=tls_context()``, not merely some context:
    ``context=None`` or an unverified context would restore the bug."""
    for keyword in call.keywords:
        if keyword.arg == "context":
            value = keyword.value
            return isinstance(value, ast.Call) and getattr(value.func, "id", "") == "tls_context"
    return False


def test_the_shared_context_verifies_against_certifi():
    ctx = tls_context()
    assert ctx is tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname
    assert Path(certifi.where()).is_file()
    loaded = len(ctx.get_ca_certs())
    assert loaded > 50
    # Provenance, not just size: a system store of the same size would still
    # prove nothing about what the packaged app trusts.
    from_certifi_only = ssl.create_default_context(cafile=certifi.where())
    assert loaded == len(from_certifi_only.get_ca_certs())


def test_wiring_every_urlopen_in_the_app_passes_a_context():
    """Source pin and absence guard: the shipped sources must hold at least
    one urlopen call and every one must pass ``context=tls_context()``. No
    behavioral seam can show this, because the claim is about the shipped
    source itself; ``test_the_shared_context_verifies_against_certifi``
    proves the context those calls pass."""
    calls = _urlopen_calls()
    assert calls, "census found no urlopen calls; the guard would pass vacuously"
    bare = [f"{path.relative_to(_ROOT)}:{node.lineno}" for path, node in calls if not _passes_shared_context(node)]
    assert not bare, f"urlopen without context=tls_context(): {bare}"

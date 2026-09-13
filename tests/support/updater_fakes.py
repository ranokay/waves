"""Updater stand-ins shared by the updater and audit test modules.

``make_manifest`` builds the signed-manifest body the updater consumes, and
``prep_updater`` wires an AppUpdater whose download writes the given payload
and whose manifest, signature and embedded key are as given. The platform
swap is stubbed so a passing case records the call without touching the live
executable.
"""

from __future__ import annotations

import hashlib

from waves.waves_ui import updater as u
from waves.waves_ui.updater import AppUpdater, Release

ASSET = "Waves.bin"


def make_manifest(payload: bytes, asset: str = ASSET, version: str = "v2.0.0") -> bytes:
    """A signed-manifest body: the CI ``# waves-version`` line (anti-rollback)
    plus a coreutils-style SHA256SUMS line pinning ``payload``'s digest to
    ``asset``."""
    line = f"{hashlib.sha256(payload).hexdigest()}  {asset}\n"
    return (f"# waves-version: {version}\n{line}").encode()


def prep_updater(monkeypatch, tmp_path, *, payload, manifest, signature, pubkey, asset=ASSET):
    """Wire an AppUpdater whose download writes ``payload`` and whose signed
    SHA256SUMS manifest, signature and embedded public key are as given."""
    monkeypatch.setattr(u, "is_frozen", lambda: True)
    monkeypatch.setattr(u, "UPDATE_PUBLIC_KEY", pubkey)
    up = AppUpdater(tmp_path, "1.0.0", repo="owner/Waves")
    up.latest = lambda *a, **k: Release(
        version="v2.0.0",
        asset=asset,
        url="http://x/" + asset,
        sha256sums_url="http://x/SHA256SUMS",
        sig_url="http://x/SHA256SUMS.sig",
    )

    def fake_download(self, sess, url, dest, progress_cb, abort):
        with open(dest, "wb") as fh:
            fh.write(payload)
        if progress_cb:
            progress_cb(100.0)

    monkeypatch.setattr(AppUpdater, "_download", fake_download, raising=True)
    monkeypatch.setattr(AppUpdater, "_fetch_manifest", lambda self, sess, url: manifest, raising=True)
    monkeypatch.setattr(AppUpdater, "_fetch_signature", lambda self, sess, url: signature, raising=True)
    applied = {}
    monkeypatch.setattr(
        AppUpdater, "_apply", lambda self, p, rel, log, abort=None: applied.setdefault("path", p) or p, raising=True
    )
    return up, applied

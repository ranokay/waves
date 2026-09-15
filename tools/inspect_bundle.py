#!/usr/bin/env python
"""Inspect a built Waves bundle against spec §10.1 (ADR 0004).

The signed application must not carry Apple-derived engine material: no APK,
no N_m3u8DL-RE binary, no wrapper image and no wrapper session/guest
libraries. Those are provisioned at setup through the managed-runtime flow.
The open-source client libraries (gamdl, yt-dlp) are ordinary dependencies
under ADR 0004 and are reported, never failed unless
``--strict-clients`` is given. Pure-Python packages are often compiled into
the main executable, so its module markers are scanned as well as the
bundle's files.

The classification is name-based by design: it catches engine artifacts
shipped under their real names, not bytes renamed to something innocent. A
content audit of every file belongs to the distribution review, not here.

Usage:

    python tools/inspect_bundle.py <path/to/waves.app|waves.dist> [--json] [--no-signature]
                                   [--strict-clients] [--require-developer-id]

Exit status 0 when no forbidden artifact is found, the client policy holds
and, on macOS with a ``.app`` bundle, codesign verifies. 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Engine material that must never ship: classified by basename.
_FORBIDDEN = (
    (re.compile(r".*\.(apk|apkm|xapk)$", re.IGNORECASE), "APK"),
    (re.compile(r".*N_m3u8DL-RE.*", re.IGNORECASE), "N_m3u8DL-RE binary"),
    (re.compile(r"^(apple-runtime|wrapper-data)$", re.IGNORECASE), "managed runtime directory"),
    (re.compile(r"^frida.*", re.IGNORECASE), "APK guest library (frida)"),
    (re.compile(r"^lib(apple|wrapper|session).*", re.IGNORECASE), "APK guest library"),
)
# Open-source clients that legitimately ship (ADR 0004): reported for the
# record, never a failure. Pure-Python packages are often compiled into the
# main executable, so the binary's module markers are scanned too.
_CLIENTS = (
    (re.compile(r"^gamdl(\.dist-info)?$", re.IGNORECASE), "gamdl"),
    (re.compile(r"^yt_dlp(\.dist-info)?$", re.IGNORECASE), "yt-dlp"),
)
_EMBEDDED_MARKERS = (
    (re.compile(r"^gamdl(\.|$)"), "gamdl"),
    (re.compile(r"^yt_dlp(\.|$)"), "yt-dlp"),
)


def _default_runner(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)  # noqa: S603 (fixed argv from this tool)


def _signature(bundle: Path, runner, platform: str) -> dict:
    """The code-signature verdict for an .app bundle (or "not-applicable")."""
    if platform != "darwin" or bundle.suffix != ".app":
        return {"checked": False, "verified": False, "kind": "not-applicable", "detail": ""}
    try:
        verify = runner(["codesign", "--verify", "--deep", "--strict", str(bundle)])
        detail = runner(["codesign", "-dv", "--verbose=2", str(bundle)])
    except FileNotFoundError:
        return {"checked": True, "verified": False, "kind": "unavailable", "detail": "codesign is not on PATH"}
    text = f"{detail.stderr or ''}{detail.stdout or ''}"
    if "Signature=adhoc" in text:
        kind = "ad-hoc"
    elif "Authority=Developer ID" in text:
        kind = "Developer ID"
    elif "Authority=Apple Development" in text:
        kind = "Apple Development"
    else:
        kind = "unknown"
    detail_line = ""
    for line in text.splitlines():
        if "Signature=" in line or "Authority=" in line:
            detail_line = line.strip()
    return {"checked": True, "verified": verify.returncode == 0, "kind": kind, "detail": detail_line}


def _scan_targets(bundle: Path) -> list[Path]:
    """The bundle's top-level files (where pure-Python modules are embedded)."""
    roots = [bundle / "Contents" / "MacOS"] if bundle.suffix == ".app" else [bundle]
    out: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        out.extend(entry for entry in sorted(root.iterdir()) if entry.is_file())
    return out


def _embedded_clients(binaries: list[Path], runner) -> list[str]:
    """Client module markers inside the executables, by name."""
    found: dict[str, str] = {}
    for binary in binaries:
        try:
            text = runner(["strings", "-a", str(binary)]).stdout or ""
        except (FileNotFoundError, UnicodeDecodeError):  # strings absent or binary decoded badly
            continue
        lines = text.splitlines()
        for pattern, client in _EMBEDDED_MARKERS:
            if client not in found and any(pattern.match(line) for line in lines):
                found[client] = f"{client}: embedded in {binary.name}"
    return list(found.values())


def inspect_bundle(
    bundle: str | Path,
    *,
    runner=None,
    verify_signature: bool = True,
    strict_clients: bool = False,
    require_developer_id: bool = False,
    platform: str | None = None,
) -> dict:
    """Classify a bundle's contents, clients and (on macOS) its signature.

    ``strict_clients`` fails the report when an open-source client ships (the
    ADR 0004 alternative); ``require_developer_id`` fails anything that is not
    a verified Developer ID signature, for release pipelines.
    """
    path = Path(bundle)
    if not path.exists():
        raise FileNotFoundError(str(path))
    runner = runner or _default_runner
    target_platform = platform or sys.platform
    forbidden: list[dict] = []
    clients: list[str] = []
    for entry in sorted(path.rglob("*")):
        name = entry.name
        rel = str(entry.relative_to(path))
        for pattern, kind in _FORBIDDEN:
            if pattern.match(name):
                forbidden.append({"path": rel, "kind": kind})
                break
        else:
            for pattern, client in _CLIENTS:
                if pattern.match(name):
                    clients.append(f"{client}: {rel}")
                    break
    seen = {item.split(":", 1)[0] for item in clients}
    clients.extend(item for item in _embedded_clients(_scan_targets(path), runner) if item.split(":", 1)[0] not in seen)
    signature = (
        _signature(path, runner, target_platform)
        if verify_signature
        else {"checked": False, "verified": False, "kind": "skipped", "detail": ""}
    )
    signature_ok = not signature["checked"] or signature["verified"]
    if require_developer_id:
        signature_ok = signature["checked"] and signature["verified"] and signature["kind"] == "Developer ID"
    ok = not forbidden and signature_ok and (not strict_clients or not clients)
    return {
        "bundle": str(path),
        "forbidden": forbidden,
        "clients": clients,
        "signature": signature,
        "policy": {"strict_clients": strict_clients, "require_developer_id": require_developer_id},
        "ok": ok,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bundle", help="waves.app (macOS) or waves.dist (Linux/Windows)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--no-signature", action="store_true", help="skip the codesign check")
    parser.add_argument("--strict-clients", action="store_true", help="fail when a client ships (ADR 0004 alternative)")
    parser.add_argument("--require-developer-id", action="store_true", help="require a verified Developer ID signature")
    args = parser.parse_args(argv)

    report = inspect_bundle(
        args.bundle,
        verify_signature=not args.no_signature,
        strict_clients=args.strict_clients,
        require_developer_id=args.require_developer_id,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"bundle: {report['bundle']}")
        for item in report["forbidden"]:
            print(f"FORBIDDEN {item['kind']}: {item['path']}")
        for client in report["clients"]:
            print(f"client shipped (ADR 0004): {client}")
        sig = report["signature"]
        if sig["checked"]:
            state = "verified" if sig["verified"] else "FAILED to verify"
            print(f"signature: {sig['kind']} ({state})")
        else:
            print(f"signature: {sig['kind']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

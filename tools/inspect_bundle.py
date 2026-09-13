#!/usr/bin/env python
"""Inspect a built Waves bundle against spec §10.1 (ADR 0004).

The signed application must not carry Apple-derived engine material: no APK,
no N_m3u8DL-RE binary, no wrapper image and no wrapper session/guest
libraries. Those are provisioned at setup through the managed-runtime flow.
The open-source client libraries (gamdl, yt-dlp) are ordinary dependencies
under ADR 0004 and are reported, never failed.

Usage:

    python tools/inspect_bundle.py <path/to/waves.app|waves.dist> [--json] [--no-signature]

Exit status 0 when no forbidden artifact is found and, on macOS with a
``.app`` bundle, codesign verifies. 1 otherwise.
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
    (re.compile(r".*\.apkm?$", re.IGNORECASE), "APK"),
    (re.compile(r"^N_m3u8DL-RE(\.exe)?$", re.IGNORECASE), "N_m3u8DL-RE binary"),
    (re.compile(r"^(apple-runtime|wrapper-data)$", re.IGNORECASE), "managed runtime directory"),
    (re.compile(r"^waves-wrapper-v2.*", re.IGNORECASE), "wrapper image"),
)
# Open-source clients that legitimately ship (ADR 0004): reported for the
# record, never a failure.
_CLIENTS = (
    (re.compile(r"^gamdl(\.dist-info)?$", re.IGNORECASE), "gamdl"),
    (re.compile(r"^yt_dlp(\.dist-info)?$", re.IGNORECASE), "yt-dlp"),
)


def _default_runner(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)  # noqa: S603 (fixed argv from this tool)


def _signature(bundle: Path, runner) -> dict:
    """The macOS code-signature verdict for an .app bundle."""
    if sys.platform != "darwin" or bundle.suffix != ".app":
        return {"checked": False, "verified": False, "kind": "not-applicable", "detail": ""}
    verify = runner(["codesign", "--verify", "--deep", "--strict", str(bundle)])
    detail = runner(["codesign", "--verify", "--verbose=2", str(bundle)])
    text = f"{detail.stderr or ''}{detail.stdout or ''}"
    if "Signature=adhoc" in text:
        kind = "ad-hoc"
    elif "Authority=" in text:
        kind = "Developer ID"
    else:
        kind = "unknown"
    return {
        "checked": True,
        "verified": verify.returncode == 0,
        "kind": kind,
        "detail": text.strip().splitlines()[-1] if text.strip() else "",
    }


def inspect_bundle(bundle: str | Path, *, runner=None, verify_signature: bool = True) -> dict:
    """Classify a bundle's contents and (on macOS) its signature."""
    path = Path(bundle)
    if not path.exists():
        raise FileNotFoundError(str(path))
    runner = runner or _default_runner
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
    signature = (
        _signature(path, runner)
        if verify_signature
        else {"checked": False, "verified": False, "kind": "skipped", "detail": ""}
    )
    ok = not forbidden and (not signature["checked"] or signature["verified"])
    return {
        "bundle": str(path),
        "forbidden": forbidden,
        "clients": clients,
        "signature": signature,
        "ok": ok,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bundle", help="waves.app (macOS) or waves.dist (Linux/Windows)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--no-signature", action="store_true", help="skip the codesign check")
    args = parser.parse_args(argv)

    report = inspect_bundle(args.bundle, verify_signature=not args.no_signature)
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

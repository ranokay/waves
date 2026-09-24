#!/usr/bin/env python
"""Generate third-party license notices for a built Waves bundle.

Reads the build environment's installed distributions (the locked venv) via
importlib.metadata, writes ``THIRD_PARTY_NOTICES`` beside the app plus the
license texts under ``licenses/``. Qt/PySide6 ships as separate shared
libraries (never static-linked; the static-only QML plugin is pruned), so the
LGPL relinking path stays the shared-library replacement.

Usage: python tools/generate_third_party_notices.py <bundle-dir>
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
from pathlib import Path

_LICENSE_NAMES = ("LICENSE", "COPYING", "NOTICE", "LICENSE.rst", "LICENSE.txt")


def _license_of(dist: metadata.Distribution) -> str:
    return dist.metadata.get("License-Expression") or dist.metadata.get("License") or "UNKNOWN"


def _home_of(dist: metadata.Distribution) -> str:
    home = dist.metadata.get("Home-page") or ""
    if home:
        return home
    for url in dist.metadata.get_all("Project-URL") or []:
        label, _, href = url.partition(",")
        if label.strip().lower() in ("homepage", "home", "repository", "source"):
            return href.strip()
    return ""


def _dist_name(dist: metadata.Distribution) -> str:
    return dist.metadata.get("Name") or "UNKNOWN"


def collect() -> list[dict]:
    rows = []
    for dist in metadata.distributions():
        name = _dist_name(dist)
        rows.append(
            {
                "name": name,
                "version": dist.version,
                "license": _license_of(dist),
                "home": _home_of(dist),
                "dist": dist,
            }
        )
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def _copy_texts(row: dict, licenses_dir: Path) -> list[str]:
    dist = row["dist"]
    copied: list[str] = []
    for f in dist.files or []:
        if f.name in _LICENSE_NAMES or f.name.startswith("LICENSE"):
            src = dist.locate_file(f)
            try:
                text = src.read_bytes()
            except (FileNotFoundError, IsADirectoryError):
                continue
            target = licenses_dir / f"{row['name']}-{f.name}"
            target.write_bytes(text)
            copied.append(target.name)
    if not copied:
        stub = licenses_dir / f"{row['name']}-NOTICE.txt"
        stub.write_text(
            f"{row['name']} {row['version']}\nLicense: {row['license']}\n"
            f"Home: {row['home'] or 'see package metadata'}\n"
            "Full text not shipped in the wheel; see the upstream source.\n"
            "Qt/PySide6: https://www.qt.io/licensing/ and https://www.gnu.org/licenses/\n",
        )
        copied.append(stub.name)
    return copied


def generate(bundle: str | Path) -> Path:
    out = Path(bundle)
    out.mkdir(parents=True, exist_ok=True)
    licenses_dir = out / "licenses"
    licenses_dir.mkdir(exist_ok=True)
    rows = collect()
    lines = [
        "Waves third-party notices",
        "===========================",
        "",
        "Generated from the build environment's installed metadata (uv.lock).",
        "LGPL libraries (Qt/PySide6, tidalapi) ship as separate shared",
        "libraries, never static-linked, so the relinking path is library replacement.",
        "",
    ]
    for row in rows:
        copied = _copy_texts(row, licenses_dir)
        home = f" <{row['home']}>" if row["home"] else ""
        lines.append(f"- {row['name']} {row['version']}: {row['license']}{home} [{', '.join(copied)}]")
    notice = out / "THIRD_PARTY_NOTICES"
    notice.write_text("\n".join(lines) + "\n")
    return notice


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", help="bundle dir (dist/waves.app or dist/waves.dist)")
    args = parser.parse_args(argv)
    notice = generate(args.bundle)
    print(f"wrote {notice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

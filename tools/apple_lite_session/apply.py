"""Check or apply the pinned source extension without reading runtime state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def _source_error(source: Path, inputs: dict[str, str], outputs: dict[str, str]) -> str:
    for name, digest in inputs.items():
        candidate = source / name
        try:
            matches = (
                not candidate.is_symlink()
                and not candidate.parent.is_symlink()
                and candidate.is_file()
                and hashlib.sha256(candidate.read_bytes()).hexdigest() == digest
            )
        except OSError:
            matches = False
        if not matches:
            return "The source prerequisites do not match the checked snapshot."
    for name in outputs:
        if name not in inputs and (source / name).exists():
            return "An extension file already exists. Preserve it and use a fresh source copy."
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Write the checked source extension")
    args = parser.parse_args()
    source = args.source.resolve()
    package = Path(__file__).resolve().parent
    manifest = json.loads((package / "manifest.json").read_text())
    patch = package / "session-observer.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest["patch_sha256"]:
        print("The source extension does not match its manifest.")
        return 1
    error = _source_error(source, manifest["inputs"], manifest["outputs"])
    if error:
        print(error)
        return 1
    git = shutil.which("git")
    if git is None:
        print("Git is required to apply the source extension.")
        return 1
    patch_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    patch_env["GIT_CEILING_DIRECTORIES"] = str(source.parent)
    try:
        checked = subprocess.run(  # noqa: S603 (fixed git operation, exact-hash source and patch)
            [git, "apply", "--unidiff-zero", "--check", str(patch)],
            cwd=source,
            env=patch_env,
            capture_output=True,
            timeout=15,
        )
        if checked.returncode:
            print("The checked source extension cannot be applied.")
            return 1
        if not args.apply:
            print("The checked source extension is applicable. No files were written.")
            return 0
        applied = subprocess.run(  # noqa: S603 (explicit --apply writes only the checked source files)
            [git, "apply", "--unidiff-zero", str(patch)], cwd=source, env=patch_env, capture_output=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        print("The source extension command failed.")
        return 1
    if applied.returncode:
        print("The source extension command failed.")
        return 1
    for name, digest in manifest["outputs"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            print("The applied source does not match the expected extension.")
            return 1
    print("The source extension was applied. Build and native qualification remain required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

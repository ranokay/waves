"""Check pyupgrade rewrites on disposable copies or apply explicit fixes."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def check_files(files: list[str]) -> int:
    # One pyupgrade process keeps whole-tree checks comparable to its batch CLI.
    # It rewrites disposable copies, never reviewed files or the index.
    with tempfile.TemporaryDirectory(prefix="waves-pyupgrade-") as directory:
        pairs = []
        for index, name in enumerate(files):
            original = Path(name)
            copy = Path(directory) / f"{index}.py"
            copy.write_bytes(original.read_bytes())
            pairs.append((original, copy))
        if not pairs:
            return 0
        result = subprocess.run(
            [sys.executable, "-m", "pyupgrade", "--py312-plus", *[str(copy) for _, copy in pairs]],
            capture_output=True,
            check=False,
        )
        for original, copy in pairs:
            if original.read_bytes() != copy.read_bytes():
                print(f"{original}: needs pyupgrade; run mise run fmt", file=sys.stderr)
        if result.returncode:
            diagnostics = result.stdout + result.stderr
            for original, copy in pairs:
                diagnostics = diagnostics.replace(os.fsencode(copy), os.fsencode(original))
            sys.stderr.buffer.write(diagnostics)
        return int(result.returncode != 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    if args.fix and args.files:
        # pyupgrade treats a literal '-' as stdin even after its option delimiter.
        files = [str(Path(name).absolute()) for name in args.files]
        result = subprocess.run(
            [sys.executable, "-m", "pyupgrade", "--py312-plus", "--", *files], capture_output=True, check=False
        )
        if result.returncode == 0:
            return 0
        if result.returncode != 1:
            sys.stderr.buffer.write(result.stdout + result.stderr)
            return result.returncode
        # pyupgrade exits 1 for rewrites as well as unsupported input. Recheck
        # disposable copies so a completed fix succeeds and real failures remain.
    return check_files(args.files)


if __name__ == "__main__":
    sys.exit(main())

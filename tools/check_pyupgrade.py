"""Report pyupgrade's additional rewrites without changing the input files."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    # One pyupgrade process keeps whole-tree checks comparable to its batch CLI.
    # It rewrites disposable copies, never reviewed files or the index.
    with tempfile.TemporaryDirectory(prefix="waves-pyupgrade-") as directory:
        pairs = []
        for index, name in enumerate(sys.argv[1:]):
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
        if result.returncode and not result.stderr.startswith(b"Rewriting "):
            sys.stderr.buffer.write(result.stderr)
        return int(result.returncode != 0)


if __name__ == "__main__":
    sys.exit(main())

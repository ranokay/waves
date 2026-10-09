"""Compare qmlformat's stdout with source using the project's pinned style."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    failed = False
    for name in sys.argv[1:]:
        result = subprocess.run(["pyside6-qmlformat", "-s", ".qmlformat.ini", name], capture_output=True, check=False)
        if result.returncode:
            sys.stderr.buffer.write(result.stderr)
            failed = True
        elif result.stdout != Path(name).read_bytes():
            print(f"{name}: needs qmlformat; run mise run fmt", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())

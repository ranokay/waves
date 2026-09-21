#!/usr/bin/env python
"""Select release matrix legs for the `only` filter.

The release-or-test-build workflow builds one matrix job per selected leg;
legs the filter excludes never become jobs, so their conclusions can never
read as green builds. Selection keeps the filter's documented substring
rule: a leg builds when its `os_arch` appears in the `only` input, which is
why naming a legacy leg also runs its regular twin. Blank input selects
every leg (releases and test-build pushes).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def select_legs(legs: list[dict], only: str) -> list[dict]:
    only = (only or "").strip()
    if not only:
        return list(legs)
    return [leg for leg in legs if leg["os_arch"] in only]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: select_build_legs.py <legs-json> <only>", file=sys.stderr)
        return 2
    legs_path = Path(argv[1])
    if not legs_path.resolve().is_relative_to(Path.cwd().resolve()):
        print(f"refusing legs file outside the checkout: {argv[1]!r}", file=sys.stderr)
        return 1
    legs = json.loads(legs_path.read_text(encoding="utf-8"))["legs"]
    selected = select_legs(legs, argv[2])
    if argv[2].strip() and not selected:
        print(f"no legs match only={argv[2]!r}", file=sys.stderr)
        return 1
    print(json.dumps(selected, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

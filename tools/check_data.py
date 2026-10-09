"""Validate TOML and single-document YAML without rewriting them."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import yaml


def main() -> int:
    failed = False
    for name in sys.argv[1:]:
        path = Path(name)
        try:
            if path.suffix == ".toml":
                tomllib.loads(path.read_text(encoding="utf-8"))
            else:
                yaml.safe_load(path.read_text(encoding="utf-8"))
        except (ValueError, yaml.YAMLError) as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())

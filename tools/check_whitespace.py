"""Check or explicitly fix whitespace while retaining the repository's byte rules."""

from __future__ import annotations

import argparse
from pathlib import Path


def end_of_file(source: bytes) -> bytes:
    if not source:
        return source
    if source[-1:] not in (b"\n", b"\r"):
        return source + b"\n"
    body = source.rstrip(b"\r\n")
    if not body:
        return b""
    suffix = source[len(body) :]
    terminator = b"\r\n" if suffix.startswith(b"\r\n") else suffix[:1]
    return body + terminator


def trailing_whitespace(source: bytes) -> bytes:
    lines = source.split(b"\n")
    for index, line in enumerate(lines):
        # CRLF is a terminator; a lone CR is trailing whitespace. Retain each
        # line's own terminator, including an unterminated final line.
        if index < len(lines) - 1 and line.endswith(b"\r"):
            lines[index] = line[:-1].rstrip() + b"\r"
        else:
            lines[index] = line.rstrip()
    return b"\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("eof", "trailing"))
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    transform = end_of_file if args.kind == "eof" else trailing_whitespace
    failed = False
    for name in args.files:
        path = Path(name)
        original = path.read_bytes()
        expected = transform(original)
        if original != expected:
            if args.fix:
                path.write_bytes(expected)
            else:
                print(f"{name}: needs {args.kind} whitespace fix; run mise run fmt")
                failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
# qmllint gate for the QML tree.
#
# Syntax failures always fail, and the incompatible-type category is raised to
# error (qmllint's defaults call type mismatches warnings) so a real type error
# fails too. Everything else stays at qmllint's levels: the tree's thousands of
# `[unqualified]` notes are warnings, counted and summarized on success so they
# cannot bury a failure; on failure the full output is printed (syntax problems
# arrive as `Warning: ... [syntax]`, which the error filter alone would hide).
# Pass file paths to lint just those (the pre-commit hook does); with no
# arguments the whole tree is linted.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

FILES=()
if [ "$#" -gt 0 ]; then
  FILES=("$@")
else
  # bash 3.2 (macOS) has no mapfile; a read loop is the portable shape.
  while IFS= read -r f; do
    [ -n "$f" ] && FILES+=("$f")
  done < <(find waves/waves_ui/qml -type f \( -name '*.qml' -o -name '*.js' \) | LC_ALL=C sort)
fi
if [ "${#FILES[@]}" -eq 0 ]; then
  echo "qmllint: no QML files found" >&2
  exit 1
fi

out="$(uv run --locked --all-extras pyside6-qmllint \
  --incompatible-type error \
  "${FILES[@]}" 2>&1)"
rc=$?

errors="$(printf '%s\n' "$out" | grep -c '^Error' || true)"
warnings="$(printf '%s\n' "$out" | grep -c '^Warning' || true)"

if [ "$rc" -ne 0 ]; then
  printf '%s\n' "$out"
fi
echo "qmllint: ${errors:-0} errors, ${warnings:-0} warnings across ${#FILES[@]} file(s)"
exit "$rc"

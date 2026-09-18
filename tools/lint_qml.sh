#!/usr/bin/env bash
# qmllint gate for the QML tree.
#
# Type and resolution categories are raised to error, so a real type error
# fails the run (qmllint's defaults call them warnings); the tree's thousands
# of `[unqualified]` notes stay warnings and are counted, not printed, so they
# cannot bury an error in CI logs. Pass file paths to lint just those (the
# pre-commit hook does); with no arguments the whole tree is linted.
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

if [ "${errors:-0}" -gt 0 ]; then
  printf '%s\n' "$out" | grep -A2 '^Error' || true
fi
echo "qmllint: ${errors:-0} errors, ${warnings:-0} warnings across ${#FILES[@]} file(s)"
exit "$rc"

#!/usr/bin/env bash
# qmllint gate for the QML tree.
#
# Errors fail the run (qmllint's own exit code); warnings are counted and
# summarized instead of printed, because the tree carries thousands of
# `[unqualified]` notes that would otherwise bury the errors in CI logs.
# Pass file paths to lint just those (the pre-commit hook does); with no
# arguments the whole tree is linted.
set -uo pipefail
cd "$(dirname "$0")/.."

if [ "$#" -gt 0 ]; then
  FILES=("$@")
else
  FILES=(waves/waves_ui/qml/*.qml waves/waves_ui/qml/*.js)
fi

out="$(uv run --locked --all-extras pyside6-qmllint "${FILES[@]}" 2>&1)"
rc=$?

errors="$(printf '%s\n' "$out" | grep -c '^Error' || true)"
warnings="$(printf '%s\n' "$out" | grep -c '^Warning' || true)"

if [ "${errors:-0}" -gt 0 ]; then
  printf '%s\n' "$out" | grep -A2 '^Error' || true
fi
echo "qmllint: ${errors:-0} errors, ${warnings:-0} warnings across ${#FILES[@]} file(s)"
exit "$rc"

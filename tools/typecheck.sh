#!/usr/bin/env bash
# ty gate for the shipped package (waves/).
#
# Errors fail. The warnings are the accepted seam baseline that pyproject.toml
# scopes to its documented files (DEVELOPER.md, `mise run typecheck`), several
# hundred of them, so they are counted rather than printed: printed in full they bury
# the error that failed the run. Every other line ty prints (errors, config
# problems) passes through, one line per diagnostic. Extra arguments go to
# `ty check`.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

out="$(uv run --locked --all-extras ty check --output-format concise "$@" 2>&1)"
rc=$?

errors="$(printf '%s\n' "$out" | grep -c ': error\[' || true)"
warnings="$(printf '%s\n' "$out" | grep -c ': warning\[' || true)"

printf '%s\n' "$out" | grep -v -e ': warning\[' -e '^Found [0-9]* diagnostics' -e '^All checks passed' | grep -v '^$' || true
echo "ty: ${errors:-0} errors, ${warnings:-0} baseline warnings"
exit "$rc"

#!/usr/bin/env bash
# ty gate for the shipped package (waves/).
#
# Errors fail. The accepted warning baseline is each rule that a [tool.ty]
# override in pyproject.toml downgrades to "warn", in the files that override
# names (DEVELOPER.md, `mise run typecheck`): several hundred warnings, so
# those are counted rather than printed, since printed in full they bury the
# error that failed the run. Every other line ty prints passes through, one
# per diagnostic: errors, ty's own default-warn rules, warnings from any other
# file (a config typo such as an unknown rule is a warning in pyproject.toml),
# crashes. Override `include` entries are matched as literal paths: a glob
# entry's warnings print instead of being counted. Extra arguments go to
# `ty check`.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

# Reading pyproject.toml needs only the standard library: no project
# environment, so nothing is built or installed to read it.
baseline="$(uv run --no-project --no-build python - <<'PY'
import tomllib

with open("pyproject.toml", "rb") as f:
    overrides = tomllib.load(f)["tool"]["ty"].get("overrides", [])
print(",".join(
    f"{path}|{rule}"
    for override in overrides
    for path in override.get("include", [])
    for rule, level in override.get("rules", {}).items()
    if level == "warn"
))
PY
)" || exit 1

out="$(uv run --locked --all-extras ty check --output-format concise --color never "$@" 2>&1)"
rc=$?

printf '%s\n' "$out" | awk -v baseline="$baseline" -v rc="$rc" '
  BEGIN { n = split(baseline, pairs, ","); for (i = 1; i <= n; i++) base[pairs[i]] = 1 }
  /(^|: )error[\[:]/ { errors++ }
  /: warning\[/ {
    split($0, parts, ":")
    if (match($0, /warning\[[a-z-]+\]/) && (parts[1] "|" substr($0, RSTART + 8, RLENGTH - 9)) in base) { hidden++; next }
  }
  /^Found [0-9]+ diagnostics?$/ || /^All checks passed/ || /^$/ { next }
  { print }
  END {
    printf "ty: %d errors, %d baseline warnings\n", errors, hidden
    if (rc != 0) printf "ty: exit %d; `uv run ty check <file>` shows each error with its code frame\n", rc
  }'
exit "$rc"

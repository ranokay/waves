#!/usr/bin/env bash
# ty gate for the shipped package (waves/).
#
# Errors fail. The accepted warning baseline is the warnings in the files
# pyproject.toml's [tool.ty] overrides name (DEVELOPER.md, `mise run
# typecheck`), several hundred of them, so those are counted rather than
# printed: printed in full they bury the error that failed the run. Every
# other line ty prints passes through, one per diagnostic: errors, warnings
# from any other file (a config typo such as an unknown rule is a warning in
# pyproject.toml), crashes. Extra arguments go to `ty check`.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

baseline="$(uv run --locked --all-extras python - <<'PY'
import tomllib

with open("pyproject.toml", "rb") as f:
    overrides = tomllib.load(f)["tool"]["ty"].get("overrides", [])
print(",".join(path for override in overrides for path in override.get("include", [])))
PY
)" || exit 1

out="$(uv run --locked --all-extras ty check --output-format concise "$@" 2>&1)"
rc=$?

printf '%s\n' "$out" | awk -v baseline="$baseline" '
  BEGIN { n = split(baseline, files, ","); for (i = 1; i <= n; i++) base[files[i]] = 1 }
  /: error\[/ { errors++ }
  /: warning\[/ { split($0, parts, ":"); if (parts[1] in base) { hidden++; next } }
  /^Found [0-9]+ diagnostics?$/ || /^All checks passed/ || /^$/ { next }
  { print }
  END {
    printf "ty: %d errors, %d baseline warnings\n", errors, hidden
    if (errors) print "ty: `uv run ty check <file>` shows each error with its code frame"
  }'
exit "$rc"

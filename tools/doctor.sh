#!/usr/bin/env bash
# doctor: fail fast on the stale-install and hook states DEVELOPER.md describes.
# Prints versions, then one line per check with its fix. Exits nonzero on any failure.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
fail=0
say() { printf '%s\n' "$*"; }
bad() { say "FAIL: $1 (fix: $2)"; fail=$((fail + 1)); }
ok() { say "ok: $1"; }

say "versions:"
command -v mise >/dev/null && say "  mise $(mise --version 2>/dev/null)" || say "  mise: not on PATH"
have_uv=0
if command -v uv >/dev/null; then
  have_uv=1
  say "  uv $(uv --version 2>/dev/null)"
else
  bad "uv not on PATH" "install uv, then mise run install"
fi
say "  python $(python3 --version 2>&1)"

# Stale editable install from the tidaler -> waves rename.
# Without uv the install state is unknown, so skip rather than misreport.
if [ "$have_uv" -eq 0 ]; then
  say "skip: uv-dependent checks need uv"
elif uv pip show tidaler >/dev/null 2>&1; then
  bad "stale 'tidaler' distribution still installed" "uv pip uninstall tidaler && mise run install"
else
  ok "no stale 'tidaler' distribution"
fi
if [ "$have_uv" -eq 0 ]; then
  :
elif uv pip show waves >/dev/null 2>&1; then
  ok "'waves' distribution installed"
else
  bad "'waves' distribution not installed (app runs as Waves-dev, looks signed out)" "mise run install"
fi

# Lockfile is the environment.
if [ "$have_uv" -eq 0 ]; then
  :
elif uv lock --check >/dev/null 2>&1; then
  ok "uv.lock in sync"
else
  bad "uv.lock drift" "uv sync --all-extras (or mise run install)"
fi

# Verify the effective repository hook configuration, including linked worktrees.
if [ "$have_uv" -eq 0 ]; then
  :
elif uv run --locked --all-extras --no-sync python tools/install_hooks.py --check; then
  ok "hk hooks verified"
else
  bad "hk hooks missing or stale" "mise run install"
fi
if command -v hk >/dev/null; then
  say "  hk $(hk --version 2>/dev/null)"
else
  bad "hk not on PATH" "mise install"
fi

# QML smoke without Qt: the entry file exists and the package imports.
if [ -f waves/desktop/qml/Main.qml ]; then
  ok "qml/Main.qml present"
else
  bad "qml/Main.qml missing" "reconcile the checkout against develop"
fi
if [ "$have_uv" -eq 0 ]; then
  :
elif uv run --locked --no-sync python -c "import waves" >/dev/null 2>&1; then
  ok "'import waves' resolves"
else
  bad "'import waves' fails" "mise run install"
fi

[ "$fail" -eq 0 ] && say "doctor: all checks pass" || say "doctor: $fail check(s) failed"
exit "$fail"

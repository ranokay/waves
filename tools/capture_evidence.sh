#!/usr/bin/env bash
# capture_evidence.sh: repeat the durable checks behind docs/evidence/ to stdout.
# Narrow scope: bundle + wrapper-image provenance only. Ordinary test/build logs
# stay in CI. Writes nowhere unless --dest FILE is given; never latest-run files.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
dest=""
[ "${1:-}" = "--dest" ] && { dest="${2:-}"; shift 2 2>/dev/null || true; }
[ $# -gt 0 ] && { echo "usage: capture_evidence.sh [--dest FILE]" >&2; exit 2; }
fail=0

out() { printf '%s\n' "$*"; }
run() {
  out "\$ $(printf '%q ' "$@")"
  "$@" 2>&1 || { rc=$?; out "(exit $rc)"; fail=1; }
}

rev="$(git rev-parse HEAD 2>/dev/null)" || { echo "error: cannot determine revision" >&2; exit 1; }
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [ -n "$dest" ]; then exec > >(tee "$dest"); fi

out "revision: $rev ($branch)"
out ""
out "## bundle (docs/evidence/bundle-inspection.md)"
if [ -d dist/waves.app ] || [ -d dist/waves.dist ]; then
  bundle="dist/waves.app"; [ -d dist/waves.dist ] && [ ! -d dist/waves.app ] && bundle="dist/waves.dist"
  run uv run --locked --all-extras python tools/inspect_bundle.py "$bundle"
else
  out "no bundle in dist/; build first: mise run build"
  out "then: uv run --locked --all-extras python tools/inspect_bundle.py dist/waves.app"
fi
out ""
out "## wrapper image (docs/evidence/wrapper-image-inspection.md)"
run grep -n WRAPPER_V2_IMAGE_DIGEST waves/providers/apple/runtime.py
img="$(grep -o 'ghcr.io/[^"]*' waves/providers/apple/runtime.py | head -n 1 || true)"
out "re-pull: docker pull ${img:-ghcr.io/ranokay/waves-wrapper-v2}@<digest above>"
exit "$fail"

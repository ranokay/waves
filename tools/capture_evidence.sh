#!/usr/bin/env bash
# capture_evidence.sh: repeat the durable checks behind docs/evidence/ to stdout.
# Narrow scope: bundle + wrapper-image provenance only. Ordinary test/build logs
# stay in CI. Writes nowhere unless --dest FILE is given; never latest-run files.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
dest=""
[ "${1:-}" = "--dest" ] && { dest="${2:-}"; shift 2 2>/dev/null || true; }
[ -z "$dest" ] && [ $# -gt 0 ] && { echo "usage: capture_evidence.sh [--dest FILE]" >&2; exit 2; }

out() { printf '%s\n' "$*"; }
run() {
  out "\$ $*"
  "$@" 2>&1 || out "(exit $?)"
}

{
  out "revision: $(git rev-parse HEAD) ($(git rev-parse --abbrev-ref HEAD 2>/dev/null))"
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
  out "re-pull: docker pull ghcr.io/ranokay/waves-wrapper-v2@<digest above>"
} | { if [ -n "$dest" ]; then tee "$dest"; else cat; fi; }

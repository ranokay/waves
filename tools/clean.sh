#!/usr/bin/env bash
# Remove regenerable build and test caches.
#
# Deletes only what the build and test tools recreate: the Nuitka/Flatpak
# outputs (dist, build-dir, flatpak-repo), bytecode and tool caches
# (__pycache__, .pytest_cache, .ruff_cache, .mypy_cache, .hypothesis),
# QML compile artifacts (*.qmlc, *.jsc), and the local code-review-graph
# store. Everything else is left alone: never `git clean`, never `.venv`,
# and never the deferred-channel sources under packaging/ (aur, winget).
# Idempotent: a second run removes nothing and still exits 0.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

rm -rf dist build-dir flatpak-repo .code-review-graph \
  .pytest_cache .ruff_cache .mypy_cache .hypothesis

# Next-to-source artifacts, everywhere but the venv and git metadata.
find . \( -path './.venv' -o -path './.git' \) -prune -o -type d \
  \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' \
  -o -name '.mypy_cache' -o -name '.hypothesis' \) -exec rm -rf {} +
find . \( -path './.venv' -o -path './.git' \) -prune -o -type f \
  \( -name '*.pyc' -o -name '*.pyo' -o -name '*.qmlc' -o -name '*.jsc' \) \
  -exec rm -f {} +

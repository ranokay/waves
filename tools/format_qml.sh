#!/usr/bin/env bash
# QML formatter (qmlformat) for the tree.
#
# The style is pinned by the repo-root .qmlformat.ini, not Qt's ambient
# defaults: the defaults rewrite the semicolon-free JS and let a Qt bump
# restyle the tree. With no arguments the whole tree is formatted; pass file
# paths to format just those (the tools/lint_qml.sh shape, which is also what
# the pre-commit hook hands it).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

FILES=()
if [ "$#" -gt 0 ]; then
  FILES=("$@")
else
  # bash 3.2 (macOS) has no mapfile; a read loop is the portable shape.
  while IFS= read -r f; do
    [ -n "$f" ] && FILES+=("$f")
  done < <(find waves/waves_ui/qml -type f -name '*.qml' | LC_ALL=C sort)
fi
if [ "${#FILES[@]}" -eq 0 ]; then
  echo "format-qml: no QML files found" >&2
  exit 1
fi

uv run --locked --all-extras pyside6-qmlformat -i "${FILES[@]}"

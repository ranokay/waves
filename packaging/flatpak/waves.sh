#!/bin/sh
# Flatpak entry point: the Nuitka tree lives at /app/waves (the binary inside
# it is "Waves", named after waves.py, the build entry point).
exec /app/waves/Waves "$@"

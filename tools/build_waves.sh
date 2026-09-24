#!/usr/bin/env bash
# Builds the Waves standalone app with Nuitka. This is the one build recipe:
# `mise run build` and every CI build leg call this file (the old Makefile
# target, ported verbatim).
#
# --dry-run prints the Nuitka command a host would use and exits, so tests can
# assert the flag set (OS=Windows_NT simulates the Windows default, as the
# Makefile's $(OS) did).
set -euo pipefail
cd "$(dirname "$0")/.."

DRY_RUN=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

WAVES_APP_NAME="Waves"
WAVES_VERSION="$(grep -m 1 '__version__' waves/desktop/__init__.py | tr -d ' "' | cut -d'=' -f2)"
[ -n "$WAVES_VERSION" ] || { echo "error: could not parse __version__ from waves/desktop/__init__.py" >&2; exit 1; }
DIST="dist"
# Oldest macOS the bundle can run on: the most demanding file shipped inside
# decides this, in practice the PySide6 wheels (see the note in pyproject.toml).
# The locked 6.11.1 really requires macOS 15 (its wheel tag lies),
# so 15.0 is the default; CI's legacy macOS legs overlay pyside6 6.9.3 and
# override this to 12.0 via the environment (hence the :-) for the "_legacy"
# bundles. The value is declared in Info.plist so an unsupported system shows
# a clear "requires macOS N" dialog instead of a silent Dock bounce, and CI's
# "Assert macOS version floor" step fails any build containing a file that
# demands something newer than the flavor's declared floor.
WAVES_MACOS_MIN="${WAVES_MACOS_MIN:-15.0}"

# The bundled Apple engine pulls in yt-dlp, whose generated C is huge; on
# hosted Windows runners MSVC dies compiling several of those modules at once
# ("fatal error C1002: compiler is out of heap space in pass 2"). Windows
# builds therefore default to Nuitka's low-memory mode: one C compiler job at
# a time and cheaper options. The release build cache makes the slower first
# pass a one-time cost; an environment-provided WAVES_NUITKA_FLAGS still wins.
#
# yt-dlp's lazy extractor table is excluded on every host: its
# generated C dominated the build (4,182 s of a 4,593 s cold build on Apple
# silicon) and it is the one module MSVC cannot compile at all -- the full
# record and numbers live in docs/platform-enablement-review.md. Waves never
# extracts a page URL (gamdl hands yt-dlp only direct stream URLs, so only
# yt_dlp.downloader runs), and yt-dlp's own import contract falls back to the
# real extractor modules when the table is absent (`except ImportError` in
# extractor/extractors.py), so every extractor stays in the artifact. With the
# exclusion the cold build is ~6.5 minutes and waves.app 236 MB (was ~77
# minutes, 301 MB).
#
# On Apple silicon, Nuitka's auto-downloaded ccache is an x86-64 binary (its
# cache holds one build per version), so Scons runs it under Rosetta and clang
# then fails with "unable to load libxcrun ... need 'x86_64'".
# Keep ccache out on Darwin/arm64 until an arm64 binary is provisioned; the
# other hosts keep it.
WAVES_HOST="$(uname -s 2>/dev/null)-$(uname -m 2>/dev/null)"
WAVES_NUITKA_FLAGS="${WAVES_NUITKA_FLAGS:-}"
if [ -z "$WAVES_NUITKA_FLAGS" ]; then
  case "${OS:-}" in
    Windows_NT) WAVES_NUITKA_FLAGS="--low-memory" ;;
    *) if [ "$WAVES_HOST" = "Darwin-arm64" ]; then WAVES_NUITKA_FLAGS="--disable-ccache"; fi ;;
  esac
fi
WAVES_NUITKA_FLAGS="$WAVES_NUITKA_FLAGS --nofollow-import-to=yt_dlp.extractor.lazy_extractors"

# PyCryptodome's native modules (_raw_aes, _SHA1, ...) are loaded by name
# through ctypes (load_pycryptodome_raw_lib), which Nuitka's import following
# cannot see. --include-package pulls only the package's Python submodules, so
# without these explicit includes the bundle ships an empty Crypto/Cipher and
# Apple downloads die at the first native load ("Cannot load native module
# 'Crypto.Cipher._raw_aes'", then 'Crypto.Hash._SHA1'). The list
# is the native set of the pinned PyCryptodome on the reference platform; the
# packaging tests fail on a stale name and require every signing/download
# module to be listed (x86_64-only AES-NI/CLMUL extras are copied through
# Nuitka's implicit-import table), and tools/inspect_bundle.py fails a bundle
# that dropped one of the required modules.
WAVES_CRYPTO_NATIVE=(
  Crypto.Cipher._ARC4 Crypto.Cipher._Salsa20 Crypto.Cipher._chacha20
  Crypto.Cipher._pkcs1_decode Crypto.Cipher._raw_aes
  Crypto.Cipher._raw_arc2 Crypto.Cipher._raw_blowfish Crypto.Cipher._raw_cast
  Crypto.Cipher._raw_cbc Crypto.Cipher._raw_cfb Crypto.Cipher._raw_ctr
  Crypto.Cipher._raw_des Crypto.Cipher._raw_des3 Crypto.Cipher._raw_ecb
  Crypto.Cipher._raw_eksblowfish Crypto.Cipher._raw_ocb Crypto.Cipher._raw_ofb
  Crypto.Hash._BLAKE2b Crypto.Hash._BLAKE2s Crypto.Hash._MD2 Crypto.Hash._MD4
  Crypto.Hash._MD5 Crypto.Hash._RIPEMD160 Crypto.Hash._SHA1
  Crypto.Hash._SHA224 Crypto.Hash._SHA256 Crypto.Hash._SHA384
  Crypto.Hash._SHA512 Crypto.Hash._ghash_portable Crypto.Hash._keccak
  Crypto.Hash._poly1305 Crypto.Math._modexp Crypto.Protocol._scrypt
  Crypto.PublicKey._curve25519 Crypto.PublicKey._curve448
  Crypto.PublicKey._ec_ws Crypto.PublicKey._ed25519 Crypto.PublicKey._ed448
  Crypto.Util._cpuid_c Crypto.Util._strxor
)
CRYPTO_ARGS=()
for module in "${WAVES_CRYPTO_NATIVE[@]}"; do
  CRYPTO_ARGS+=("--include-module=$module")
done

# The environment is whatever uv has synced into .venv (mise run install, or
# the CI setup action); a legacy CI leg overlays its Qt wheels there and this
# must not resync it. A fresh checkout with no venv falls through to uv, which
# then installs the locked environment including the gui extra.
if [ -x .venv/bin/python ]; then
  WAVES_PYTHON=(.venv/bin/python)
elif [ -x .venv/Scripts/python.exe ]; then
  WAVES_PYTHON=(.venv/Scripts/python.exe)
else
  WAVES_PYTHON=(uv run --locked --all-extras python)
fi

# Qt 6.11 ships Qt.labs.assetdownloader as a static library only, which Nuitka
# cannot process (see tools/prune_static_qml_plugins.py). Prune it from the
# build virtualenv first; a no-op on Qt versions without it.
if [ -n "$DRY_RUN" ]; then
  echo "prune: ${WAVES_PYTHON[*]} tools/prune_static_qml_plugins.py"
  echo "nuitka: MACOSX_DEPLOYMENT_TARGET=$WAVES_MACOS_MIN WAVES_NUITKA_FLAGS=$WAVES_NUITKA_FLAGS ${WAVES_PYTHON[*]} -m nuitka --macos-app-version=$WAVES_VERSION --file-version=$WAVES_VERSION --product-version=$WAVES_VERSION --macos-app-name=$WAVES_APP_NAME --output-filename=$WAVES_APP_NAME --product-name=$WAVES_APP_NAME ${CRYPTO_ARGS[*]} waves.py"
  exit 0
fi

"${WAVES_PYTHON[@]}" tools/prune_static_qml_plugins.py

# MACOSX_DEPLOYMENT_TARGET: without it, everything Nuitka compiles inherits
# the build host's own macOS version as its floor, and CI's "Assert macOS
# version floor" step rejects the bundle. Harmless on Linux/Windows.
# shellcheck disable=SC2086 -- the flag string must word-split, Nuitka takes it as separate args.
MACOSX_DEPLOYMENT_TARGET="$WAVES_MACOS_MIN" "${WAVES_PYTHON[@]}" -m nuitka \
  $WAVES_NUITKA_FLAGS \
  --macos-app-version="$WAVES_VERSION" \
  --file-version="$WAVES_VERSION" \
  --product-version="$WAVES_VERSION" \
  --macos-app-name="$WAVES_APP_NAME" \
  --output-filename="$WAVES_APP_NAME" \
  --product-name="$WAVES_APP_NAME" \
  "${CRYPTO_ARGS[@]}" \
  waves.py

# Strip the Qt modules the QML UI never loads (chiefly a ~210 MB bundled
# Chromium), see tools/trim_qt_bundle.sh, which auto-detects the per-OS
# bundle layout (waves.app on macOS, waves.dist on Linux/Windows).
if [ -d "$DIST/waves.app" ]; then
  bash tools/trim_qt_bundle.sh "$DIST/waves.app"
  echo "🔐 Declaring network/removable volume access so macOS shows a persistable consent prompt (no Full Disk Access needed)"
  plutil -replace NSNetworkVolumesUsageDescription -string "Waves saves your downloads to the folder you choose, which can live on a network share (NAS/SMB)." "$DIST/waves.app/Contents/Info.plist"
  plutil -replace NSRemovableVolumesUsageDescription -string "Waves saves your downloads to the folder you choose, which can live on an external drive." "$DIST/waves.app/Contents/Info.plist"
  echo "🧱 Declaring the macOS floor so older systems get a clear dialog instead of a silent bounce"
  plutil -replace LSMinimumSystemVersion -string "$WAVES_MACOS_MIN" "$DIST/waves.app/Contents/Info.plist"
  echo "🔏 Re-sealing macOS bundle (trim + plist edit broke Nuitka's ad-hoc signature)"
  codesign --force --deep --sign - "$DIST/waves.app"
elif [ -d "$DIST/waves.dist" ]; then
  bash tools/trim_qt_bundle.sh "$DIST/waves.dist"
fi

# Third-party notices ride every bundle (DEP-09): generated from the locked
# venv's metadata plus the license texts, beside the app in each layout.
if [ -d "$DIST/waves.app" ]; then
  "${WAVES_PYTHON[@]}" tools/generate_third_party_notices.py "$DIST/waves.app"
elif [ -d "$DIST/waves.dist" ]; then
  "${WAVES_PYTHON[@]}" tools/generate_third_party_notices.py "$DIST/waves.dist"
fi

# Spec §10.1 (ADR 0004): no Apple-derived engine material may ship; the
# open-source clients are reported. Fails the build on forbidden material.
if [ -d "$DIST/waves.app" ]; then
  "${WAVES_PYTHON[@]}" tools/inspect_bundle.py "$DIST/waves.app"
elif [ -d "$DIST/waves.dist" ]; then
  "${WAVES_PYTHON[@]}" tools/inspect_bundle.py "$DIST/waves.dist"
fi

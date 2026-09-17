WAVES_APP_NAME = "Waves"
WAVES_VERSION=`grep -m 1 '__version__' waves/waves_ui/__init__.py | tr -d ' "' | cut -d'=' -f2`
app_path_dist = "dist"
# Oldest macOS the bundle can run on: the most demanding file shipped inside
# decides this, in practice the PySide6 wheels (see the note in pyproject.toml).
# The locked 6.11.1 really requires macOS 15 (its wheel tag lies, issue #14),
# so 15.0 is the default; CI's legacy macOS legs overlay pyside6 6.9.3 and
# override this to 12.0 via the environment (hence ?=) for the "_legacy"
# bundles. The value is declared in Info.plist so an unsupported system shows
# a clear "requires macOS N" dialog instead of a silent Dock bounce, and CI's
# "Assert macOS version floor" step fails any build containing a file that
# demands something newer than the flavor's declared floor.
WAVES_MACOS_MIN ?= 15.0

# The bundled Apple engine pulls in yt-dlp, whose generated C is huge; on
# hosted Windows runners MSVC dies compiling several of those modules at once
# ("fatal error C1002: compiler is out of heap space in pass 2"). Windows
# builds therefore default to Nuitka's low-memory mode: one C compiler job at
# a time and cheaper options. The release build cache makes the slower first
# pass a one-time cost; an empty value opts back into parallelism.
#
# yt-dlp's lazy extractor table is excluded on every host (issue #245): its
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
# then fails with "unable to load libxcrun ... need 'x86_64'" (issue #243).
# Keep ccache out on Darwin/arm64 until an arm64 binary is provisioned; the
# other hosts keep it.
WAVES_HOST := $(shell uname -s 2>/dev/null)-$(shell uname -m 2>/dev/null)
WAVES_NUITKA_FLAGS ?= $(if $(filter Windows_NT,$(OS)),--low-memory,$(if $(filter Darwin-arm64,$(WAVES_HOST)),--disable-ccache,))
# Appended, not part of the ?= default: the exclusion is a packaging fact about
# yt-dlp, not a host choice, and the CI Windows legs prefix the command with
# WAVES_NUITKA_FLAGS=--low-memory (an environment value a ?= default would
# never apply to). A command-line WAVES_NUITKA_FLAGS=... override still wins --
# the usual escape hatch for a one-off build.
WAVES_NUITKA_FLAGS += --nofollow-import-to=yt_dlp.extractor.lazy_extractors

.PHONY: install
install: ## Install the poetry environment and install the pre-commit hooks
	@echo "🚀 Creating virtual environment using pyenv and poetry"
	@poetry install --all-extras --with dev
	@poetry run pre-commit install
	@poetry shell

.PHONY: check
check: ## Run code quality tools.
	@echo "🚀 Checking Poetry lock file consistency with 'pyproject.toml': Running poetry lock --check"
	@poetry check --lock
	@echo "🚀 Linting code: Running pre-commit"
	@poetry run pre-commit run -a
	@echo "🚀 Checking for obsolete dependencies: Running deptry"
	@poetry run deptry .

.PHONY: test
test: ## Test the code with pytest
	@echo "🚀 Testing code: Running pytest"
	@poetry run pytest --doctest-modules

.PHONY: test-fast
test-fast: ## Run the fast group (no Qt, ffmpeg, slow, integration or account; < 1 min)
	@echo "🚀 Testing code: fast group"
	@poetry run pytest --doctest-modules -rs -q -m "not qml and not ffmpeg and not slow and not account and not integration" tests

.PHONY: test-qml
test-qml: ## Run the quick QML group (Qt required; < 5 min)
	@echo "🚀 Testing code: quick QML group"
	@poetry run pytest --doctest-modules -rs -q -m "qml and not slow and not integration and not account" --require-qml tests

.PHONY: test-default
test-default: ## Run the default group (all but the live account tests; < 10 min)
	@echo "🚀 Testing code: default group"
	@poetry run pytest --doctest-modules -rs -m "not account" tests

.PHONY: test-strict
test-strict: ## Run the merge gate (everything but the live account tests; < 10 min)
	@echo "🚀 Testing code: strict group"
	@poetry run pytest --doctest-modules -rs --require-qml -m "not account" tests

.PHONY: test-ffmpeg
test-ffmpeg: ## Run the ffmpeg group (assumes ffmpeg on PATH; < 1 min)
	@echo "🚀 Testing code: ffmpeg group"
	@poetry run pytest --doctest-modules -rs -q -m "ffmpeg and not account" tests

.PHONY: star-history
star-history: ## Copy the star-history chart from the public repo into this tree
	@bash tools/sync_star_history.sh

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: gui-waves
gui-waves: ## Build the Waves QML app (standalone). On macOS this yields dist/waves.app
	@# Qt 6.11 ships Qt.labs.assetdownloader as a static library only, which
	@# Nuitka cannot process (see tools/prune_static_qml_plugins.py). Prune it
	@# from the build virtualenv first; a no-op on Qt versions without it.
	@poetry run python tools/prune_static_qml_plugins.py
	@# MACOSX_DEPLOYMENT_TARGET: without it, everything Nuitka compiles inherits
	@# the build host's own macOS version as its floor, and CI's "Assert macOS
	@# version floor" step rejects the bundle. Harmless on Linux/Windows.
	@MACOSX_DEPLOYMENT_TARGET=$(WAVES_MACOS_MIN) poetry run python -m nuitka \
		$(WAVES_NUITKA_FLAGS) \
		--macos-app-version=$(WAVES_VERSION) \
		--file-version=$(WAVES_VERSION) \
		--product-version=$(WAVES_VERSION) \
		--macos-app-name=$(WAVES_APP_NAME) \
		--output-filename=$(WAVES_APP_NAME) \
		--product-name=$(WAVES_APP_NAME) \
		waves.py
	@# Strip the Qt modules the QML UI never loads (chiefly a ~210 MB bundled
	@# Chromium), see tools/trim_qt_bundle.sh, which auto-detects the per-OS
	@# bundle layout (waves.app on macOS, waves.dist on Linux/Windows).
	@if [ -d "$(app_path_dist)/waves.app" ]; then \
		bash tools/trim_qt_bundle.sh "$(app_path_dist)/waves.app"; \
		echo "🔐 Declaring network/removable volume access so macOS shows a persistable consent prompt (no Full Disk Access needed)"; \
		plutil -replace NSNetworkVolumesUsageDescription -string "Waves saves your downloads to the folder you choose, which can live on a network share (NAS/SMB)." "$(app_path_dist)/waves.app/Contents/Info.plist"; \
		plutil -replace NSRemovableVolumesUsageDescription -string "Waves saves your downloads to the folder you choose, which can live on an external drive." "$(app_path_dist)/waves.app/Contents/Info.plist"; \
		echo "🧱 Declaring the macOS floor so older systems get a clear dialog instead of a silent bounce"; \
		plutil -replace LSMinimumSystemVersion -string "$(WAVES_MACOS_MIN)" "$(app_path_dist)/waves.app/Contents/Info.plist"; \
		echo "🔏 Re-sealing macOS bundle (trim + plist edit broke Nuitka's ad-hoc signature)"; \
		codesign --force --deep --sign - "$(app_path_dist)/waves.app"; \
	elif [ -d "$(app_path_dist)/waves.dist" ]; then \
		bash tools/trim_qt_bundle.sh "$(app_path_dist)/waves.dist"; \
	fi
	@# Spec §10.1 (ADR 0004): no Apple-derived engine material may ship; the
	@# open-source clients are reported. Fails the build on forbidden material.
	@if [ -d "$(app_path_dist)/waves.app" ]; then \
		poetry run python tools/inspect_bundle.py "$(app_path_dist)/waves.app"; \
	elif [ -d "$(app_path_dist)/waves.dist" ]; then \
		poetry run python tools/inspect_bundle.py "$(app_path_dist)/waves.dist"; \
	fi

# Per-OS aliases used by CI (release-or-test-build.yml). The build + trim already
# happens in gui-waves; CI zips the result (macOS = waves.app, Linux/Windows =
# waves.dist). They exist as named entry points so each matrix leg reads clearly.
.PHONY: gui-waves-linux
gui-waves-linux: gui-waves ## Build + trim the Waves app (Linux); artifact is dist/waves.dist

.PHONY: gui-waves-windows
gui-waves-windows: gui-waves ## Build + trim the Waves app (Windows); artifact is dist/waves.dist

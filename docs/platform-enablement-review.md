# Windows and Linux enablement review

- Status: in progress (item 25, issue #205) — CI bundle runs still executing
- Scope: what the Windows and Linux builds ship, how the platform-dependent
  code branches behave, and which claims are verified versus still open
- Method: code audit of every `platform`/`sys.platform` branch and the release
  matrix, plus real CI runs on the fork's runners

## Platform matrix

The release workflow builds eight legs: macOS intel/arm64 (regular, floor 15)
and legacy (PySide6 6.9.3, floor 12), Linux x64/arm64, Windows x64/arm64.
Linux legs ship a zip and an AppImage; Windows legs ship a zip. A
smoke-launch step runs the trimmed bundle offscreen for **non-arm64** legs
only; the arm64 legs build but do not launch their artifacts.

Tests run in the manual `master` workflow on ubuntu-24.04 only (Python 3.12
and 3.13 plus the quality job). There is no Windows or macOS test leg.

## Code audit: platform branches and their intent

| Area                                                | Branch                | Behavior                                                                                                                                                 |
| --------------------------------------------------- | --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Config location (`helper/path.py`)                  | darwin / win32 / else | Native Application Support / `%APPDATA%` / XDG; legacy `~/.config` migration preserved                                                                   |
| Reveal and open (`backend.py`, `bridge_library.py`) | all                   | `QDesktopServices.openUrl`, Qt's per-platform handler (no shell-specific calls)                                                                          |
| Taskbar identity (`app.py`)                         | win32                 | Explicit AppUserModelID before the first window; applies to frozen builds too                                                                            |
| Launch tuning (`app.py`)                            | darwin                | Proxy lookup memoization; a no-op elsewhere                                                                                                              |
| Network mounts (`netmount.py`, `smb_relist.py`)     | darwin                | macOS volume watching; other platforms use the plain watcher                                                                                             |
| Remote-folder detection (`bridge_library.py`)       | win32                 | Mapped-drive device strings + `GetDriveTypeW(DRIVE_REMOTE)` on top of the fstype check                                                                   |
| Memory units (`diagnostics.py`)                     | darwin / else         | Correct units per platform                                                                                                                               |
| Apple runtime (`providers/apple/runtime.py`)        | all                   | Per-platform N_m3u8DL-RE asset table with SHA-256, `.exe` naming on Windows; gentle container start is macOS-only by design (others get wizard guidance) |
| Library scanner child (`library_proc.py`)           | all                   | Frozen builds re-exec themselves; source runs use `sys.executable -m`; `CREATE_NO_WINDOW` on Windows                                                     |
| Updater (`updater.py`)                              | all                   | os/arch asset selection, macOS legacy flavor, package-manager guards (AppImage/Snap/Flatpak/Homebrew/Scoop)                                              |
| FFmpeg manager (`ffmpeg_manager.py`)                | all                   | martin-riedl for macOS/Linux, BtbN builds for Windows; `.exe` naming                                                                                     |
| Library worker (`library_worker.py`)                | all                   | Stdlib-only child process; symlink-aware walk                                                                                                            |

## CI evidence

- **Linux tests on develop**: master run `34928309207` (2026-09-15) — quality,
  tox 3.12 and tox 3.13 all green.
- **Linux x64 and Windows x64 bundles**: release-or-test-build run
  `34928310777` (in progress; includes the offscreen smoke-launch).
- **Linux arm64 and Windows arm64 bundles**: run `34929398611` (queued behind
  the first by the workflow's concurrency group; build only, no smoke-launch).

## Gaps and risks

1. **No Windows/macOS test execution**: only bundle builds validate those
   platforms. A regression that only breaks tests (not the build) goes unseen.
2. **arm64 artifacts are not smoke-launched**, so "builds" is the strongest
   claim for Linux/Windows arm64.
3. **The wrapper image is `linux/arm64` only.** x86_64 hosts (Windows x64,
   Linux x64, Intel Macs) can only run it under QEMU/binfmt; the full Apple
   tier's performance and reliability there are unverified (spec §10.5's
   "image architecture for x86-64 hosts").
4. **No live account or container verification** on Windows or Linux; the
   opt-in account suite has only run on macOS Apple silicon.
5. Windows arm64 runners are migrating to Visual Studio 2026 on 2026-09-21
   (runner annotation); the build leg may need revalidation then.

## Recommendations

- Add a fast-domain test job for Windows (no QML/ffmpeg markers) to the manual
  workflow; it is the cheapest way to catch pure-Python platform breaks.
- Either smoke-launch arm64 artifacts or state in the workflow why not, so
  "built" is not mistaken for "runs".
- Decide the x86_64 container story (an amd64 image variant, or documented
  QEMU-only support) before advertising the full Apple tier on Windows/Linux.
- Run the opt-in account suite once on a real Windows and a real Linux desktop
  before calling those platforms verified.

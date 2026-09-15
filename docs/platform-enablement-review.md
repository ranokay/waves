# Windows and Linux enablement review

- Status: review complete and the Windows mitigation is in the build; the
  verification run is pending (issue #205)
- Scope: what the Windows and Linux builds ship, how the platform-dependent
  code branches behave, and which claims are verified versus still open
- Method: code audit of the platform branches in production code (paths,
  mounts, runtime assets, child processes, updater) and the release matrix,
  plus real CI runs on the fork's runners

## Platform matrix

The release workflow builds eight legs: macOS intel/arm64 (regular, floor 15)
and legacy (PySide6 6.9.3, floor 12), Linux x64/arm64, Windows x64/arm64.
Linux legs ship a zip and an AppImage; Windows legs ship a zip. A
smoke-launch step runs the trimmed bundle offscreen on every leg whose
`OS_ARCH` does not end in `-arm64` — all four macOS legs and both x64 legs;
only the Linux and Windows arm64 legs build without launching.

Tests run in the manual `master` workflow on ubuntu-24.04 only (Python 3.12
and 3.13 plus the quality job). There is no Windows or macOS test leg.

## Code audit: platform branches and their intent

| Area                                                           | Branch                | Behavior                                                                                                                                                                          |
| -------------------------------------------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Config location (`helper/path.py`)                             | darwin / win32 / else | Native Application Support / `%APPDATA%` / XDG; legacy `~/.config` migration preserved                                                                                            |
| Path length cap (`helper/path.py`)                             | win32 / else          | Whole-path cap 259 on Windows / 1023 elsewhere, measured the way the platform measures it (UTF-16 units, bytes on POSIX); rename and download planning trust it, not pathvalidate |
| Mount recovery (`backend.py`)                                  | darwin                | `/Volumes` watcher and keep-warm probe, `diskutil unmount force` after idle ejections; a no-op elsewhere                                                                          |
| Settings writes (`config.py`)                                  | win32                 | Bounded retry when `os.replace` hits a `WinError 32` sharing violation; a single attempt elsewhere                                                                                |
| Path identity (`providers/apple/integrity.py`, `ownership.py`) | nt / darwin           | Case-folded comparisons where the platform folds them (Windows, macOS); exact on Linux                                                                                            |
| Reveal and open (`backend.py`, `bridge_library.py`)            | all                   | `QDesktopServices.openUrl`, Qt's per-platform handler (no shell-specific calls)                                                                                                   |
| Taskbar identity (`app.py`)                                    | win32                 | Explicit AppUserModelID before the first window; applies to frozen builds too                                                                                                     |
| Launch tuning (`app.py`)                                       | darwin                | Proxy lookup memoization; a no-op elsewhere                                                                                                                                       |
| Network mounts (`netmount.py`, `smb_relist.py`)                | darwin                | macOS volume watching; other platforms use the plain watcher                                                                                                                      |
| Remote-folder detection (`bridge_library.py`)                  | win32                 | Mapped-drive device strings + `GetDriveTypeW(DRIVE_REMOTE)` on top of the fstype check                                                                                            |
| Memory units (`diagnostics.py`)                                | darwin / else         | Correct units per platform                                                                                                                                                        |
| Apple runtime (`providers/apple/runtime.py`)                   | all                   | Per-platform N_m3u8DL-RE asset table with SHA-256, `.exe` naming on Windows; gentle container start is macOS-only by design (others get wizard guidance)                          |
| Library scanner child (`library_proc.py`)                      | all                   | Frozen builds re-exec themselves; source runs use `sys.executable -m`; `CREATE_NO_WINDOW` on Windows                                                                              |
| Updater (`updater.py`)                                         | all                   | os/arch asset selection, macOS legacy flavor, package-manager guards (AppImage/Snap/Flatpak/Homebrew/Scoop)                                                                       |
| FFmpeg manager (`ffmpeg_manager.py`)                           | all                   | martin-riedl for macOS/Linux, BtbN builds for Windows; `.exe` naming                                                                                                              |
| Library worker (`library_worker.py`)                           | all                   | Stdlib-only child process; symlink-aware walk                                                                                                                                     |

## CI evidence (2026-09-15, all at `b67bc72`)

| Leg           | Run           | Result                 | Detail                                                                                                                                                  |
| ------------- | ------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Linux x64     | `34928310777` | built + smoke-launched | 1h53m build; the offscreen smoke-launch passed                                                                                                          |
| Linux arm64   | `34929398611` | built                  | 3h53m; no smoke-launch by design                                                                                                                        |
| Windows x64   | `34928310777` | **failed**             | MSVC `fatal error C1002: compiler is out of heap space in pass 2` after 2h29m, on yt-dlp's `youtube.jsc._builtin.ejs` and `lazy_extractors` generated C |
| Windows arm64 | `34929398611` | **failed**             | the same C1002 on `lazy_extractors`, after 2h45m                                                                                                        |

Linux tests on develop are green in the same window (master run `34928309207`:
quality, tox 3.12 and tox 3.13).

Reading note: the workflow's `only` filter still creates every matrix job;
legs the filter excludes finish "success" with every step skipped, so job
conclusions alone can look like passes. The failed Windows jobs are genuine
build attempts; the raw logs live in the run pages above.

## Why Windows fails while Linux passes

Upstream's v0.1.29 release built both Windows legs in ~14 minutes (run
`34766640853`; the x64 build step took 13m50s and the smoke-launch passed).
The difference is the bundled Apple engine: the fork's app imports gamdl,
which imports every yt-dlp extractor, so Nuitka compiles roughly 1,700 extra
C modules — two of them enormous. MSVC runs out of heap when several of those
compile at once on a 16 GB hosted runner. The Linux legs compile the same
sources with GCC/clang at full parallelism and only pay time, not memory.

The causal check: upstream's tree has no providers package at all and its
`pyproject.toml` has no gamdl entry; the Apple engine exists only in this
fork. Upstream's 14-minute build is the same workflow without the engine.

## Mitigation

The bundled engine needs Nuitka's low-memory mode on Windows:

- `WAVES_NUITKA_FLAGS` in the Makefile defaults to `--low-memory` on Windows
  (`OS=Windows_NT`) and is empty elsewhere; the release workflow's two Windows
  legs also set it explicitly, so the flag cannot be lost to make's
  environment detection. Nuitka then runs one C compiler job at a time with
  cheaper options.
- The release build cache's input hash now covers the Makefile, `pyproject.toml`
  and the workflow, so the slower cold pass is paid once per leg and a flag or
  toolchain change never reuses a mismatched tree.

Verification: run `35019374456` builds both Windows legs from this branch
(dispatched 2026-09-15); the outcome lands here and in
`docs/audits/apple-music-2026-09-11/evidence/platform-builds-2026-09-15.md`.
If the heap failure survives serial compilation, the next options are a larger
runner for those two legs or dropping yt-dlp's lazily generated extractor
module from the bundle — which would change the bundling contract ADR 0004
decided and needs its own decision, not a build-flag tweak.

## Gaps and risks

1. **No Windows/macOS test execution**: only bundle builds validate those
   platforms. A regression that only breaks tests (not the build) goes unseen.
2. **arm64 artifacts are not smoke-launched**, so "builds" is the strongest
   claim for Linux/Windows arm64.
3. **The wrapper image is `linux/arm64` only.** x86_64 hosts (Windows x64,
   Linux x64, Intel Macs) can only run it under QEMU/binfmt; the full Apple
   tier's performance and reliability there are unverified.
4. **No live account or container verification** on Windows or Linux; the
   opt-in account suite has only run on macOS Apple silicon.
5. **Windows builds are memory-bound by the bundled engine**: the low-memory
   mitigation is unverified at the time of writing, the first cold build per
   leg is long, and the six-hour job limit is the ceiling. Windows arm64
   runners migrate to Visual Studio 2026 on 2026-09-21; revalidate then.

## Recommendations

- Land the low-memory run green before calling Windows verified; keep the flag
  until a larger runner or a compiler-side fix removes the heap ceiling.
- Add a fast-domain test job for Windows (no QML/ffmpeg markers) to the manual
  workflow; it is the cheapest way to catch pure-Python platform breaks.
- Either smoke-launch arm64 artifacts or state in the workflow why not, so
  "built" is not mistaken for "runs".
- Decide the x86_64 container story (an amd64 image variant, or documented
  QEMU-only support) before advertising the full Apple tier on Windows/Linux.
- Run the opt-in account suite once on a real Windows and a real Linux desktop
  before calling those platforms verified.

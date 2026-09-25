# Windows and Linux enablement review

- Status: review complete; Linux verified; Windows bundle builds revalidated
  green on the exclusion recipe (run
  [35836125855](https://github.com/ranokay/waves/actions/runs/35836125855),
  2026-09-23; ADR 0009 superseded). The body below is the 2026-09-21 review as
  written: its Windows-build blocker is resolved, while gaps 1–4 and the
  test-job and live-verification recommendations stay owed
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

Tests run in the manual `master` workflow on ubuntu-24.04 only (Python 3.12,
3.13 and 3.14 plus the quality job). There is no Windows or macOS test leg.

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

## CI evidence

The run-by-run tables used to live here; they now live in a single place,
`docs/evidence/platform-builds.md`, which this document no longer duplicates.
Status: the Windows park is lifted — run
[35836125855](https://github.com/ranokay/waves/actions/runs/35836125855)
(2026-09-23) revalidated both Windows legs on the exclusion recipe
(`windows-2022` built and smoke-launched healthy, `windows-11-arm` built),
and ADR 0009 is superseded accordingly. The fast test jobs for Windows and
macOS (#439) are wired into the manual workflow; their first runs are still
owed, as is the opt-in account suite on those platforms (see Gaps below).

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

## Mitigation and outcome

The first patch gave Windows builds Nuitka's low-memory mode: `--low-memory`
through `WAVES_NUITKA_FLAGS` (build-script default on `OS=Windows_NT`, set
explicitly by the workflow's Windows legs), one C compiler job at a time. The
release build cache's input hash covers the build script, `mise.toml`,
`pyproject.toml` and the workflow, so the slower cold pass is paid once per
leg.

Verification run `35019374456` (both Windows legs, 2026-09-15/16) confirmed
the flag reached Nuitka and failed anyway, on one module:

- windows-x64: `cl` stack overflow (`Error 3221225725` = `0xC00000FD`) while
  compiling `yt_dlp.extractor.lazy_extractors`.
- windows-arm64: `fatal error C1002: compiler is out of heap space` on the
  same module.

Serial compilation removed the parallelism pressure, not the module. Every
other module — yt-dlp's 1,751 individual extractors and the second-largest
generated file included — compiles. The blocker is yt-dlp's generated
`lazy_extractors.py` (186k lines of generated C), and it is the only module
either leg cannot compile.

Options assessed for the parked fix:

- **Exclude `yt_dlp.extractor.lazy_extractors` with `--nofollow-import-to=…`
  — adopted 2026-09-17.** yt-dlp catches the resulting
  `ImportError` and falls back to the eager extractor list. All 1,751
  extractors stay available (verified locally by blocking the import in the
  source tree, and again in a compiled Nuitka probe: all 1,751 classes);
  yt-dlp's first use gets slower, and Waves never makes one — gamdl only ever
  hands yt-dlp a direct stream URL (`HlsFD`/`HttpFD`), so the extractor
  machinery is never touched. The table was also the single biggest cost of
  every _working_ build: on macOS arm64 its 58.8 MiB of generated C took
  2,040 s of clang and 2,142 s of Python optimization — 4,182 s of a 4,593 s
  cold build — and a warm rebuild paid it again. With the exclusion the cold
  build is 385 s (6 m 26 s) and a warm rebuild 379 s (no object reuse either
  way), the peak process RSS 1.31 GB warm / 1.14 GB cold (was 2.22 GB), and
  `waves.app` 236 MB (was 301 MB), with `tools/inspect_bundle.py` passing and
  the packaged app booting clean offscreen.
- Drop the Apple engine from the Windows bundle (an ADR 0004 amendment).
- A larger runner — the x64 failure is `cl`'s own stack, so memory alone may
  not remove it.

Decision (2026-09-16, historical — superseded by the revalidation in CI
evidence above): park Windows and record the blocker; Windows artifacts
stay unpublished for now. The low-memory mode stays in place, because it is
the prerequisite for any of the options and costs only build time, which the
cache makes one-time. The exclusion above ships in
`WAVES_NUITKA_FLAGS`, so no build compiles the module.

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
5. **Windows bundle builds were blocked by the bundled engine's compile
   size.** yt-dlp's generated `lazy_extractors` module cannot be compiled by
   MSVC on hosted runners (stack overflow on x64, heap exhaustion on arm64),
   even serially. The recipe excludes that module, so no
   build compiles it; the Windows legs have since been revalidated green (run
   `35836125855`, 2026-09-23; ADR 0009 superseded) and the park is lifted.

## Recommendations

- Windows needed a successful build with the exclusion in place — done via
  the revalidation in CI evidence above (the eager fallback is proven). The
  low-memory flag stays either way. Remaining alternatives, if the recipe
  ever regresses: amend ADR 0004 to drop the engine there, or move to a
  compiler/runner that handles the module.
- Add a fast-domain test job for Windows (no QML/ffmpeg markers) to the manual
  workflow; it is the cheapest way to catch pure-Python platform breaks.
- Either smoke-launch arm64 artifacts or state in the workflow why not, so
  "built" is not mistaken for "runs".
- Decide the x86_64 container story (an amd64 image variant, or documented
  QEMU-only support) before advertising the full Apple tier on Windows/Linux.
- Run the opt-in account suite once on a real Windows and a real Linux desktop
  before calling those platforms verified.

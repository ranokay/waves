# Flatpak bundle

Builds an installable single-file Flatpak from the same Nuitka tree the Linux
release legs ship. linux-x64 only for now: the arm64 runner cannot install the
x86_64 freedesktop runtime, and a native arm64 bundle needs an arm64 runner
with flatpak support.

## Build locally

```bash
mise run build                                  # -> dist/waves.dist
flatpak-builder --repo=flatpak-repo --force-clean build-dir packaging/flatpak/org.getwaves.Waves.yml
flatpak build-bundle flatpak-repo dist/waves_linux-x64.flatpak org.getwaves.Waves
flatpak install --user -y dist/waves_linux-x64.flatpak
flatpak run org.getwaves.Waves
```

`build-dir/` and `flatpak-repo/` are transient build directories; delete them
freely.

## Sandbox

The permission set is deliberately minimal and pinned by a test:

| Permission                                                 | Why                                                                                       |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `--share=network`                                          | Every provider, the managed FFmpeg download, update checks.                               |
| `--filesystem=home`                                        | The download/library folder is user-chosen anywhere under home, and the app writes to it. |
| `--device=dri`                                             | Qt Quick renders through the GPU.                                                         |
| `--socket=pulseaudio`                                      | In-app previews and video playback.                                                       |
| `--socket=wayland`, `--socket=fallback-x11`, `--share=ipc` | A normal desktop window.                                                                  |

There is no `--filesystem=host`. A music library on a NAS, an external drive or
a path outside home needs an explicit grant, e.g.:

```bash
flatpak override --user --filesystem=/run/media org.getwaves.Waves
```

The Apple full tier (Docker/Podman sidecar) cannot run inside this sandbox; the
cookies tier and all TIDAL features are unaffected. The in-app updater already
detects Flatpak (`/.flatpak-info` / `FLATPAK_ID`) and defers to
`flatpak update`, so the bundle never tries to replace itself.

## Verification

CI builds the bundle and smoke-launches the _installed_ Flatpak offscreen for
15 seconds (a bundle that installs but never starts fails the job). Installing
and using it on a real Linux desktop — sign in, save one track, play a preview
— is a human verification step recorded on the issue, not in CI.

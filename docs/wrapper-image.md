# Publishing the Waves wrapper image

Upstream `wrapper-v2` ships source only, so Waves publishes its own pinned
image (`ghcr.io/ranokay/waves-wrapper-v2`) for end-user pulls. This page is
the maintainer runbook: one-time setup, how to publish, and the version
lockstep. End users do nothing here — Waves pulls, runs, and stops the
image itself, and Apple ID sign-in happens inside the guest at first use.

## One-time setup

1. **Host the APK privately.** Recommended: a **private repo release
   asset**. Create a private repo (e.g. `ranokay/waves-assets`), upload
   the pinned version's `.apkm` (currently **4.7.0**, arm64 — the setup
   wizard names the current pin) as a release asset, and note its
   `.../releases/download/<tag>/<file>` URL. The built-in
   `GITHUB_TOKEN` cannot cross into another private repo, so this needs
   its own credential:
   - Create a **fine-grained personal access token** with _Contents:
     read-only_ on just that repo (Settings → Developer settings →
     Personal access tokens → Fine-grained tokens). Note its expiry
     (max one year) — set a calendar reminder; an expired token fails
     the build at the download step with a 401.
   - Add two repository secrets on **this** repo (Settings → Secrets and
     variables → Actions): **`APK_URL`** = the release asset URL, and
     **`APK_AUTH_HEADER`** = the full header line
     `Authorization: Bearer <token>`. The header is sent only to fetch
     the artifact and is masked in logs.
   - Alternative without GitHub: a token-gated private bucket (R2/B2)
     with its token in `APK_AUTH_HEADER`; same shape, another account.
   - Not recommended: committing the APK anywhere, public hosting, or
     scraping app-mirror sites at build time (fragile and against their
     terms).
2. **Nothing else.** Registry auth uses the built-in `GITHUB_TOKEN`;
   Docker, QEMU, and Buildx come with the runner.

## Publishing

Actions → **wrapper-image** → Run workflow:

- `wrapper_ref` — upstream `wrapper-v2` ref to build. Prefer a full
  commit SHA for reproducibility; `main` tracks upstream.
- `image_tag` — the tag to push. **It must equal the `WRAPPER_V2_IMAGE`
  pin in `waves/apple_runtime.py`** (the suite enforces this).

The run downloads the APK, extracts and hash-verifies the arm64 native
libs against the source tree's `LIBS_VERSION.json`, builds `linux/arm64`,
smoke-tests `/health` plus the TCP decrypt port under QEMU, pushes the
tag, and prints a summary (image, source SHA, guest libs).

## After the first push: make the package public

A fresh ghcr.io package is private, and anonymous `docker pull` fails
against private packages with `denied` — which is exactly the error
end users would see. Open the package page
(`github.com/users/ranokay/packages/container/package/waves-wrapper-v2`),
Package settings → Change visibility → **Public**.

One honest caveat (spec §10.2): the image bakes Apple's `.so` files, so
a public image redistributes Apple binaries. That trade-off is the
maintainer's call; the alternatives are a private image (kills one-click
setup — every user would need `docker login` plus a grant) or a future
redesign where user-supplied libs mount at runtime instead of baking in.

## Version lockstep

These four move together; bump them as one change:

| Piece       | Where                                                            | Current   |
| ----------- | ---------------------------------------------------------------- | --------- |
| Image tag   | workflow `image_tag` input                                       | `0.2.3`   |
| Image pin   | `WRAPPER_V2_IMAGE`, `waves/apple_runtime.py`                     | `…:0.2.3` |
| APK version | `APK_PINNED_VERSION`, same file + `APK_URL` content              | `4.7.0`   |
| Guest libs  | `WRAPPER_LIBS_VERSION`, same file + upstream `LIBS_VERSION.json` | `17.0.0`  |

When upstream `wrapper-v2` fixes something you need (or Apple breaks
something it must adapt to): pick the upstream SHA, rebuild with the same
APK, and — if anything about the image changed — push a **new** tag and
move the `WRAPPER_V2_IMAGE` pin to it in the same release. Never retag a
published tag in place: machines that already pulled it would keep the
old bytes.

## Troubleshooting

- **`denied` on pull (end users):** the package flipped back to private,
  or the tag was never pushed. Check visibility, then the Actions run.
- **`APK_URL secret is not set`:** step 1 above was skipped on this repo.
- **Hash mismatch in `extract-libs.sh`:** the `APK_URL` content is the
  wrong APK version or architecture. Re-point it at the pinned version's
  arm64 release and re-run.
- **Smoke test flakes under QEMU:** emulation is slow; the health loop
  already waits two minutes. Re-run the job before suspecting the image.

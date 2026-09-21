# Bundle inspection evidence

- Revision built: `c20a2258772c84ba1ec464c3533e13e12d93a9e8` (`develop`, 2026-09-21)
- Built: 2026-09-21, macOS arm64, via `mise run build` (`tools/build_waves.sh`;
  Nuitka 2.8.4 on Python 3.13, `--disable-ccache`,
  `--nofollow-import-to=yt_dlp.extractor.lazy_extractors`)
- Inspected: `uv run --locked --all-extras python tools/inspect_bundle.py dist/waves.app`
- Inspector exit: 0

## Inspector output (verbatim)

```text
bundle: dist/waves.app
client shipped (ADR 0004): gamdl: Contents/MacOS/gamdl
client shipped (ADR 0004): yt-dlp: embedded in Waves
signature: ad-hoc (verified)
```

## Reading

- No APK, no N_m3u8DL-RE binary, no wrapper image and no guest/session
  libraries are present — the ADR 0004 boundary holds on this build.
- The open-source clients (gamdl, yt-dlp) ship as ordinary dependencies,
  exactly what ADR 0004 permits.
- The signature is ad-hoc (a local build, not the release pipeline), and it
  verifies. Release signing/notarization is a pipeline property, not
  something a local inspection can prove.

Accepted by #200; the repeatable checker is `tools/inspect_bundle.py`
(pinned by its tests).

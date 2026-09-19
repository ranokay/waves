"""Regression guard: the warm cover-art pool must ask for covers the way the
pages do, or it pins nothing.

THE BUG WE ARE FENCING OFF
--------------------------
Qt's pixmap cache is keyed on more than the url. The key is
``(url, requestRegion, requestSize, frame, providerOptions)``, and
``providerOptions`` carries the flags ``QQuickImage`` raises for
``PreserveAspectCrop`` and ``PreserveAspectFit``. Two ``Image`` elements on the
same url and the same ``sourceSize`` that differ only in ``fillMode`` are
therefore two separate cache entries: two fetches, two decodes, two pixmaps,
and neither one keeps the other alive.

Main.qml's warm pool (``warmArt`` / ``warmArtModel``) exists to hold a live
``Image`` for the last few hundred covers shown, because Qt keeps only about
2 MB of decoded-but-unreferenced pixmaps (measured on Qt 6.11: 40 to 60
thumbnails at search-row size, less than one page of results). The pool's
``Image`` was left at the default ``fillMode``, ``Image.Stretch``, while every
surface that actually paints a cover crops. So the pool fetched and decoded a
second, differently keyed copy of every cover and pinned that, the copy the
page had painted went unpinned, and a revisited page went back through the
loading placeholder as if the pool were not there. Reported from a livetest:
search, search something else, search the first thing again, and the covers
loaded from scratch.

HOW THIS STAYS FIXED
--------------------
The rule is mechanical: every ``Image`` in the cover files (Main.qml and the
component files split out of it in #315: Art.qml, PreviewArt.qml,
SearchProviderGroup.qml, MosaicCell.qml) that opts into the pixmap cache
(``cache: true``) must request its pixels the same way, so that one warmed
entry serves all of them. A new art surface that crops differently, or a pool that stops
cropping, fails here rather than silently halving the cache hit rate. The
other key components (``sourceSize``, and the properties below that would
split the key just as quietly) are pinned alongside it.

If a surface ever genuinely needs a different fill mode, it needs its own warm
entry too: teach ``warmArt`` the fill mode and key ``_warmSeen`` on it, then
add the surface here.
"""

from __future__ import annotations

import re

from support.paths import QML_MAIN as QML

# The cover surfaces live in Main.qml, Art.qml (the cover box split out in
# #315 slice 3), PreviewArt.qml (the track disc, split out in slice 5),
# SearchProviderGroup.qml (the search-group closure, split out in slice 6 —
# its cached provider mark is exempt below, but the file must stay in the
# scan set so a cover added there cannot drift from the pool unnoticed) and
# MosaicCell.qml (the browse tile's crossfade pair, split out in slice 7 —
# both Images cache): this guard must read all of them, or the app's
# most-used art surfaces stop being scanned and their cache keys can drift
# from the pool's unnoticed.
ART_QML = QML.parent / "Art.qml"
PREVIEW_ART_QML = QML.parent / "PreviewArt.qml"
SEARCH_GROUP_QML = QML.parent / "SearchProviderGroup.qml"
MOSAIC_CELL_QML = QML.parent / "MosaicCell.qml"
COVER_FILES = (QML, ART_QML, PREVIEW_ART_QML, SEARCH_GROUP_QML, MOSAIC_CELL_QML)

# The one fill mode every cover surface uses. Covers are square and so are the
# decode sizes asked for them, so cropping and stretching would paint the same
# pixels; they are simply not the same cache entry.
ART_FILL_MODE = "Image.PreserveAspectCrop"

# Properties that feed the pixmap cache key (or the request behind it) besides
# the url, the fill mode and sourceSize. None of the art surfaces sets any of
# them today; one that started to would split the key away from the pool
# exactly as the fill mode did, with no visible error.
KEY_SPLITTING_PROPS = ("sourceClipRect", "mirror", "autoTransform", "currentFrame")


_NOISE_RE = re.compile(
    r"//[^\n]*"  # line comment
    r"|/\*.*?\*/"  # block comment
    r'|"(?:\\.|[^"\\])*"'  # double-quoted string
    r"|'(?:\\.|[^'\\])*'"  # single-quoted string
    r"|`(?:\\.|[^`\\])*`",  # template literal
    re.DOTALL,
)


def _blank_noise(text: str) -> str:
    """Comments and string literals blanked out (length and newlines preserved)
    so brace matching cannot be thrown by a ``{`` inside either."""
    return _NOISE_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _image_blocks(text: str) -> list[tuple[int, str]]:
    """Every ``Image { ... }`` block: (1-based start line, block source)."""
    clean = _blank_noise(text)
    blocks: list[tuple[int, str]] = []
    for m in re.finditer(r"\bImage\s*\{", clean):
        depth, i = 0, m.end() - 1
        while i < len(clean):
            if clean[i] == "{":
                depth += 1
            elif clean[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        blocks.append((text.count("\n", 0, m.start()) + 1, clean[m.start() : i + 1]))
    return blocks


def _cached_image_blocks() -> list[tuple[str, int, str]]:
    """Every ``Image { ... }`` block that opts into the pixmap cache, in every
    file that paints a cover: (file name, 1-based start line, block source)."""
    blocks: list[tuple[str, int, str]] = []
    for path in COVER_FILES:
        text = path.read_text(encoding="utf-8")
        blocks += [(path.name, line, b) for line, b in _image_blocks(text) if re.search(r"\bcache\s*:\s*true\b", b)]
    return blocks


def test_there_are_art_images_to_check() -> None:
    """A parser that silently matched nothing would make every test below pass."""
    blocks = _cached_image_blocks()
    assert len(blocks) >= 6, f"expected the cover-art Images, found {len(blocks)}"


def test_every_cached_image_asks_for_the_same_pixels() -> None:
    """One warmed pixmap has to serve every surface that shows that cover."""
    raw = {path.name: path.read_text(encoding="utf-8").splitlines() for path in COVER_FILES}
    wrong = []
    for fname, line, block in _cached_image_blocks():
        span = raw[fname][line - 1 : line + block.count("\n")]
        joined = "\n".join(span)
        if (
            "assets/providers/" in joined
            or "modelData.logo" in joined
            or "provider.logo" in joined
            or "descriptor.logo" in joined
        ):
            # Provider marks are not covers and keep their own aspect; the
            # welcome surface and the badges take their marks from the
            # provider descriptors (issue #278).
            continue
        found = re.search(r"\bfillMode\s*:\s*(Image\.\w+)", block)
        if not found or found.group(1) != ART_FILL_MODE:
            wrong.append(f"{fname}:{line} has fillMode {found.group(1) if found else '(unset, so Image.Stretch)'}")
    assert not wrong, (
        "every cached Image must request its pixels the same way, or Qt stores it under its own "
        "pixmap-cache key and the warm pool cannot serve it:\n  " + "\n  ".join(wrong)
    )


def test_no_cached_image_splits_the_key_another_way() -> None:
    offenders = [
        f"{fname}:{line} sets {prop}"
        for fname, line, block in _cached_image_blocks()
        for prop in KEY_SPLITTING_PROPS
        if re.search(rf"\b{prop}\s*:", block)
    ]
    assert not offenders, (
        "these also change the pixmap-cache key or the request behind it, so the warm pool would "
        "stop covering the surface that sets one:\n  " + "\n  ".join(offenders)
    )


def test_the_warm_pool_image_is_one_of_them() -> None:
    """The pool entry itself, named so a reader lands on the right block."""
    text = QML.read_text(encoding="utf-8")
    pool = re.search(r"ListModel\s*\{\s*id:\s*warmArtModel\s*\}(.{0,2600}?)\n    \}\n", text, re.DOTALL)
    assert pool, "could not find the warm pool Repeater under warmArtModel"
    body = pool.group(1)
    assert "source: model.u" in body, "the warm pool stopped binding its source to the model"
    assert f"fillMode: {ART_FILL_MODE}" in body, (
        "the warm pool's Image must crop like the surfaces it warms; at the default "
        "(Image.Stretch) it pins a second copy of every cover that nothing ever paints"
    )

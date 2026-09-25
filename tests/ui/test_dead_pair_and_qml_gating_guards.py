"""Source guards against a dead bridge pair and unrenderable QML work.

The retired recentlyAdded bridge pair stays gone, the video preview passes the
same padding downloads use, ArtCard runs no collection rollups whose results
can never render, and QueueStack's marching step is gated on visible.
"""

from support.paths import QML_DIR, REPO_ROOT

BACKEND_SRC = (REPO_ROOT / "waves" / "desktop" / "backend.py").read_text()
# The whole QML tree: the negative pins below must not go vacuous when the
# surface they fence moves to another QML file.
ALL_QML = "\n".join(path.read_text(encoding="utf-8") for path in sorted(QML_DIR.glob("*.qml")))
QUEUE_STACK_QML = (QML_DIR / "QueueStack.qml").read_text()
BRIDGE_MD = (REPO_ROOT / "waves" / "desktop" / "BRIDGE.md").read_text()


# ------------------------------------------------------- retired bridge API


def test_wiring_dead_recently_added_pair_removed():
    """The retired recentlyAdded bridge pair stays gone (obsolete-API guard)."""
    assert "recentlyAdded" not in BACKEND_SRC
    assert "loadRecentlyAdded" not in BACKEND_SRC
    assert "recentlyAdded" not in ALL_QML
    assert "recentlyAddedLoaded" not in BRIDGE_MD


# ------------------------------------------------------- video preview padding


def test_wiring_video_preview_passes_padding():
    """The video preview passes the same padding downloads use (parity pin: the
    path template behavior itself is proved by the video-path-template suite)."""
    assert 'format_path_media(template, vid, pad, **kw) + ".mp4"' in BACKEND_SRC


# --------------------------------------------------- ArtCard collection rollups


def test_artcard_runs_no_unrenderable_collection_rollups():
    """Both ArtCard download controls must opt out of the collection rollup:
    one is only visible with live state (which outranks the rollup), the other
    only renders for non-collection kinds. ArtCard lives in its own file, so
    the negative pin reads the whole QML tree."""
    assert "collectionCheck: ac.kind ===" not in ALL_QML


# ------------------------------------------------------- QueueStack marching step


def test_wiring_queuestack_step_is_gated_on_visible():
    """QueueStack's marching step reads `visible` on its defining line, so the
    animation cannot depend on marchTick while hidden (single QML property: no
    cheaper seam than reading the line)."""
    line = next(ln for ln in QUEUE_STACK_QML.splitlines() if "readonly property int step:" in ln)
    assert "visible ?" in line, "step must not depend on marchTick while hidden"

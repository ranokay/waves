"""The Search tab restores ONE artist, not two halves of two.

WHAT THIS FENCES OFF
--------------------
An artist page is split-sourced. The header (photo, name, bio, DOWNLOAD
DISCOGRAPHY) reads ``artistData``; the TOP TRACKS / ALBUMS / EPS & SINGLES /
VIDEOS sections read four ListModels that only ``onArtistLoaded`` fills. Both
are shared with every other tab that can open an artist page.

A Search-tab snapshot that carries ``artistData`` but not the sections restores
two halves of two artists: open artist A from a search result, go to My Tidal,
open artist B from the Artists grid, press Search. The page comes back as A's
name, photo and bio over B's albums and top tracks, and the header's DOWNLOAD
DISCOGRAPHY button downloads A while every row on the page belongs to B.

HOW THIS STAYS FIXED
--------------------
The snapshot IS the payload the page was built from (``artistLoaded`` carries
albums/eps/tracks/videos), so the restore refills the four models from it
whenever the loaded page is a different artist. No refetch, so it also works
offline, and a restore of the artist still on screen touches nothing.

Runs in a SUBPROCESS for the same reason as test_search_scroll_reset: building
the bridge installs process-global handlers that must not leak into the rest
of the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import (
    EXIT_NO_QT,
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    run_scenario,
    sandbox_qml_settings,
)

_REGRESSED_SCOPED = 2  # the full page came back holding the favourites subset

_WIN_W, _WIN_H = 1100, 720


@pytest.mark.qml
def test_the_search_tab_restores_the_artist_it_saved():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-artistrestore-test-",
        failure_message=(
            "the restored Search view showed one artist's header over another artist's albums and tracks."
        ),
    )


def _artist(tag: str) -> dict:
    """An artistLoaded payload, the shape backend.py:4840 emits."""

    def album(i: int) -> dict:
        return {
            "id": f"{tag}al{i}",
            "title": f"{tag} Album {i}",
            "artist": f"Artist {tag}",
            "artist_id": f"{tag}id",
            "art": "",
            "year": "2020",
            "date": "2020-01-01",
            "tracks": 10,
            "quality": "LOSSLESS",
            "popularity": 60 - i,
        }

    def track(i: int) -> dict:
        return {
            "id": f"{tag}tr{i}",
            "title": f"{tag} Track {i}",
            "artist": f"Artist {tag}",
            "artist_id": f"{tag}id",
            "album": f"{tag} Album 0",
            "album_id": f"{tag}al0",
            "art": "",
            "year": "2020",
            "date": "2020-01-01",
            "duration": "3:20",
            "quality": "LOSSLESS",
            "popularity": 60 - i,
        }

    return {
        "id": f"{tag}id",
        "name": f"Artist {tag}",
        "art": "",
        "bio": f"About artist {tag}.",
        "albums": [album(i) for i in range(4)],
        "eps": [album(i + 10) for i in range(2)],
        "tracks": [track(i) for i in range(5)],
        "videos": [],
    }


def _scoped_artist(tag: str) -> dict:
    """The page My Tidal opens: the same artist, the same signal, the same id,
    holding only what the user favourited, and no videos at all."""
    payload = _artist(tag)
    payload["albums"] = payload["albums"][:1]
    payload["eps"] = []
    payload["tracks"] = payload["tracks"][:1]
    payload["libraryScoped"] = True
    return payload


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl, Slot
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from support.offline import PARK_LOGIN_QML, patch_offline

        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
    except Exception as exc:
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    patch_offline()

    loader_calls: list = []

    class _ScriptedBridge(WavesBridge):
        """The two artist loaders answer from the scenario instead of the
        network. Both exist because the Back restore has to pick the right one:
        they carry the same id through the same signal."""

        @Slot(str)
        def loadArtist(self, artist_id: str) -> None:
            loader_calls.append(("full", artist_id))
            self.artistLoaded.emit(_artist("A"))

        @Slot(str)
        def loadArtistLibrary(self, artist_id: str) -> None:
            loader_calls.append(("scoped", artist_id))
            self.artistLoaded.emit(_scoped_artist("A"))

    engine = QQmlApplicationEngine()
    bridge = _ScriptedBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    roots = engine.rootObjects()
    if not roots:
        print("Main.qml failed to load", file=sys.stderr)
        return EXIT_PRECONDITION
    root = roots[0]
    root.setProperty("width", _WIN_W)
    root.setProperty("height", _WIN_H)

    def q(expr: str):
        ctx = QQmlEngine.contextForObject(root)
        e = QQmlExpression(ctx, root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int = 200) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settle()
    q(PARK_LOGIN_QML)

    # 1. On the Search tab, the user opens artist A from a result.
    q("openSearch()")
    settle()
    if q("navOrigin") != "search":
        print(f"scenario did not start on the Search tab (navOrigin={q('navOrigin')})", file=sys.stderr)
        return EXIT_PRECONDITION
    bridge.artistLoaded.emit(_artist("A"))
    settle()
    if not q("artistOpen") or q("artistAlbumsModel.count") == 0:
        print("artist A never rendered", file=sys.stderr)
        return EXIT_PRECONDITION

    # 2. My Tidal (this is what snapshots A), then artist B from its grid.
    q("openLibrary()")
    settle()
    bridge.artistLoaded.emit(_artist("B"))
    settle()
    if q("" + "artistAlbumsModel.get(0).id") != "Bal0":
        print("artist B never took over the section models", file=sys.stderr)
        return EXIT_PRECONDITION

    # 3. Back to Search: every part of the page must be artist A again.
    q("openSearch()")
    settle()

    header = q("artistData.id")
    album0 = q("artistAlbumsModel.get(0).id")
    ep0 = q("artistEpModel.get(0).id")
    track0 = q("artistTracksModel.get(0).id")
    whole = header == "Aid" and album0 == "Aal0" and ep0 == "Aal10" and track0 == "Atr0"
    print(f"header={header} album0={album0} ep0={ep0} track0={track0} whole={whole}", flush=True)
    if not whole:
        return EXIT_REGRESSED

    # 4. The same artist again, this time the LIBRARY-SCOPED page My Tidal
    # opens: same id, same signal, same four models, but only what the user
    # favourited and no videos at all. An id-only check reads this as "the
    # page is already loaded" and leaves the subset standing under the full
    # page's header and its DOWNLOAD DISCOGRAPHY button.
    q("openLibrary()")
    settle()
    scoped = _scoped_artist("A")
    bridge.artistLoaded.emit(scoped)
    settle()
    if q("artistAlbumsModel.count") != 1:
        print("the library-scoped page never took over the section models", file=sys.stderr)
        return EXIT_PRECONDITION

    q("openSearch()")
    settle()
    albums = q("artistAlbumsModel.count")
    eps = q("artistEpModel.count")
    tracks = q("artistTracksModel.count")
    full = albums == 4 and eps == 2 and tracks == 5 and not q("artistData.libraryScoped")
    print(f"albums={albums} eps={eps} tracks={tracks} full={full}", flush=True)
    if not full:
        print(
            "the restored Search view kept the library-scoped page's favourites: the same artist"
            " opened from My Tidal filled a subset of the full page's models",
            file=sys.stderr,
        )
        return _REGRESSED_SCOPED

    # 5. Back has the same two pages to tell apart. Standing on the scoped
    # page, going to the full one pushes the SCOPED page onto the history;
    # deciding the restore on the id alone reads "already loaded" and leaves
    # the full page up, so the press does nothing and the entry is gone.
    bridge.artistLoaded.emit(scoped)
    settle()
    q("navPush()")
    bridge.artistLoaded.emit(_artist("A"))
    settle()
    if q("artistAlbumsModel.count") != 4:
        print("the full page never took over from the scoped one", file=sys.stderr)
        return EXIT_PRECONDITION

    q("navBack()")
    settle()
    back_albums = q("artistAlbumsModel.count")
    back_scoped = bool(q("artistData.libraryScoped"))
    print(f"back_albums={back_albums} back_scoped={back_scoped} loaders={loader_calls}", flush=True)
    if back_albums == 1 and back_scoped:
        return EXIT_OK
    print(
        "coming Back to Search kept the library-scoped page's favourites instead of the full page",
        file=sys.stderr,
    )
    return _REGRESSED_SCOPED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())

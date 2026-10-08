"""An artist page's opening covers are warm before the page opens.

The bridge emits `artistPagePrefetched` with the opening screen's covers --
from a hover on an already-cached page, or from a fresh build as soon as its
sections are in. Main.qml's handler must pull them into the warm pool at the
sizes the page decodes (the 150 px photo at 300, the track discs at
`discDecode`, the album and EP rows at twice `albumRowArt`), and must skip
the sections the user folded away, or the click that follows re-fetches what
the hover had just announced.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import (
    EXIT_OK,
    EXIT_REGRESSED,
    boot_main_qml,
    run_scenario,
    wait_until,
)


@pytest.mark.qml
def test_a_prefetched_artist_page_warms_its_opening_covers():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-artist-warm-test-",
        failure_message="artist page warm-pool regression",
    )


def _scenario() -> int:
    import tempfile

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QColor, QImage

    boot = boot_main_qml()
    if isinstance(boot, int):
        return boot
    _root, q, settle, bridge = boot

    # Local cover files: the warmed rows must actually decode, not just be
    # listed in the pool.
    art_dir = Path(tempfile.mkdtemp(prefix="waves-artist-warm-art-"))

    def cover(name: str, rgb: tuple) -> str:
        img = QImage(64, 64, QImage.Format.Format_RGB32)
        img.fill(QColor(*rgb))
        path = art_dir / f"{name}.png"
        img.save(str(path))
        return QUrl.fromLocalFile(str(path)).toString()

    photo = cover("photo", (40, 120, 200))
    track_arts = [cover(f"t{i}", (200, 80, 40)) for i in range(2)]
    album_arts = [cover(f"a{i}", (60, 160, 90)) for i in range(2)]
    ep_art = cover("e0", (160, 60, 90))

    def pool_rows() -> list:
        return [
            (
                str(q(f"warmArtModel.get({i}).u")),
                int(q(f"warmArtModel.get({i}).w")),
                q(f"warmArtModel.get({i}).ready"),
            )
            for i in range(int(q("warmArtModel.count")))
        ]

    disc = int(q("root.discDecode"))
    row = int(q("root.albumRowArt")) * 2
    if int(q("root.albumRowArt")) != 46:  # the shared row-cover size AlbumBlock draws at; the pool warms at 2x it
        print("regressed: the shared album row-cover size moved; revisit the warm sizes with it", file=sys.stderr)
        return EXIT_REGRESSED
    expected = {(photo, 300), *{(u, disc) for u in track_arts}, *{(u, row) for u in album_arts}, (ep_art, row)}

    bridge.artistPagePrefetched.emit(
        {
            "id": "artist-1",
            "art": photo,
            "tracks": track_arts,
            "albums": album_arts,
            "eps": [ep_art],
        }
    )
    settle(50)
    try:
        wait_until(
            lambda: expected <= {(u, w) for u, w, _ in pool_rows()},
            2000,
            message="every opening cover entered the warm pool at its page size",
        )
        wait_until(
            lambda: all(ready is True for _u, _w, ready in pool_rows()),
            3000,
            message="the warmed covers decoded",
        )
    except AssertionError as exc:
        print(f"regressed: {exc}", file=sys.stderr)
        return EXIT_REGRESSED

    # Folded sections are not warmed: a fold the user set means the page will
    # not show those rows, so warming them spends decodes on nothing.
    q("root.artistTracksCollapsed = true")
    q("root.artistAlbumsCollapsed = true")
    folded_track = cover("t2", (10, 10, 200))
    folded_album = cover("a2", (200, 10, 10))
    live_ep = cover("e2", (10, 200, 10))
    bridge.artistPagePrefetched.emit(
        {
            "id": "artist-1",
            "art": "",
            "tracks": [folded_track],
            "albums": [folded_album],
            "eps": [live_ep],
        }
    )
    settle(50)
    landed = {(u, w) for u, w, _ in pool_rows()}
    if (folded_track, disc) in landed or (folded_album, row) in landed:
        print(f"regressed: a folded section was warmed: {landed}", file=sys.stderr)
        return EXIT_REGRESSED
    if (live_ep, row) not in landed:
        print(f"regressed: the unfolded EP section was not warmed: {landed}", file=sys.stderr)
        return EXIT_REGRESSED

    print("artist page prefetch warms its opening covers at page sizes", flush=True)
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())

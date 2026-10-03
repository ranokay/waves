"""Explicit collection buttons carry their own quality context and re-ask it."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from time import monotonic

import pytest
from support.paths import QML_DIR
from support.qml import EXIT_OK, boot_main_qml, run_scenario, wait_until


@pytest.mark.qml
def test_collection_button_refreshes_its_quality_without_learned_membership():
    run_scenario(Path(__file__), "--run-scenario", sandbox_prefix="waves-collection-quality-")


def _run_scenario() -> int:
    from waves.library.ownership import OwnershipStore

    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, _settle, bridge = booted
    with tempfile.TemporaryDirectory(prefix="waves-collection-files-") as scratch:
        folder = Path(scratch)
        song = folder / "song.flac"
        song.write_bytes(b"audio")
        store = OwnershipStore(str(folder / "own.db"))
        store.record("101", str(song), "LOSSLESS", audio_mode="STEREO")
        bridge._ownership = store
        bridge._own_cache["101"] = (monotonic(), store.ownership_of("101"))
        bridge.settings.data.tidal_quality_audio = "HI_RES_LOSSLESS"
        bridge.settings.data.default_audio_type = "stereo"
        bridge._quality_overrides = {"101": "HI-RES", "album": "LOSSLESS"}
        assert store.members_of("album") is None
        source = (
            "import QtQuick\n"
            f'import "{(QML_DIR / "domains" / "downloads").as_uri()}"\n'
            'DownloadButton { host: root; mediaId: "album"; label: "Download album"; '
            'collectionIds: ["101"] }'
        )
        button = q(f"Qt.createQmlObject({json.dumps(source)}, root.contentItem, 'collection-quality-test')")
        assert button is not None
        wait_until(lambda: button.property("owned") is True, message="collection choice reaches the button")
        assert bridge.ownershipOf("101")["up_to_date"] is False
        # Only the collection id is notified: the store and object cache do
        # not know its membership. The explicit member list must still re-ask.
        bridge.setQualityOverride("album", "HI-RES")
        wait_until(lambda: button.property("owned") is False, message="collection notification invalidates ownership")
        bridge.setQualityOverride("album", "LOSSLESS")
        wait_until(lambda: button.property("owned") is True, message="collection notification restores ownership")
        bridge.setQualityOverride("album", "")
        wait_until(lambda: button.property("owned") is False, message="clearing choice uses the current default")
        button.deleteLater()
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())

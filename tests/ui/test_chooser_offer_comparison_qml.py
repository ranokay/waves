"""Rendered provider comparison: guarded switches, keyboard focus and bounds."""

from __future__ import annotations

import json
import sys

import pytest
from support.qml import boot_main_qml, run_scenario, seed_tidal_search
from support.qml_probe import scene_js


@pytest.mark.qml
def test_chooser_offer_comparison_qml():
    run_scenario(__file__, "--run-scenario", timeout=90)


def scenario():
    from providers.fakes import StubProvider
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from waves.constants import QualityTier
    from waves.metadata.catalog_identity import CatalogIdentity, CatalogLookup
    from waves.providers.base import AudioType, Capability, QualityOption, StatusKind
    from waves.providers.catalog_offers import AvailabilityEvidence

    class LocalProvider(StubProvider):
        identity_kinds = frozenset({"track"})
        quality_options = (
            QualityOption(QualityTier.LOSSLESS, "Lossless requirement"),
            QualityOption(QualityTier.HIGH, "Lossy requirement"),
        )
        audio_types = frozenset({AudioType.STEREO})
        quality_setting = "tidal_quality_audio"

        def catalog_identity_context(self):
            return ("test-account",)

        def availability_context(self):
            return ("test-account",)

        def catalog_identity(self, kind, raw_id):
            return CatalogIdentity(
                f"{self.id}:{raw_id}",
                kind,
                title="Recording",
                artist="Artist",
                identifier="USABC1200001",
                duration_ms=180000,
                explicit=False,
                version="",
                release_title="Release",
                release_version="",
            )

        def catalog_candidates(self, origin):
            return CatalogLookup((self.catalog_identity(origin.kind, "2"),))

        def probe_availability(self, identity, ask):
            return AvailabilityEvidence()

    root, q, settle, bridge = boot_main_qml()
    bridge.threadpool.waitForDone()
    providers = [
        LocalProvider(
            "tidal",
            "Origin",
            capabilities={Capability.CATALOG, Capability.DOWNLOAD, Capability.LYRICS, Capability.ART},
            status_kind=StatusKind.NONE,
            logged_in=True,
        )
    ]
    providers += [
        LocalProvider(
            f"p{i}",
            "A very long provider name with <plain text> " + str(i) * 35,
            capabilities={Capability.CATALOG, Capability.DOWNLOAD},
            status_kind=StatusKind.NONE,
            logged_in=True,
        )
        for i in range(1, 7)
    ]
    providers[0].audio_types = frozenset({AudioType.STEREO, AudioType.ATMOS})
    bridge.providers = {p.id: p for p in providers}
    bridge._provider_readiness_probes = {p.id: lambda p=p: p.readiness(enabled=True, signed_in=True) for p in providers}
    bridge.settings.data.tidal_quality_audio = QualityTier.LOSSLESS
    q(
        "legalSettings.termsAcceptedVersion = root.termsVersion; legalSettings.termsAccepted = true; setupSettings.firstRunAnswered = true; openSearch()"
    )
    seed_tidal_search(
        q,
        bridge,
        tracks=[
            {
                "id": "t1",
                "kind": "track",
                "title": "Recording",
                "artist": "Artist",
                "art": "",
                "duration": "3:00",
                "quality": "LOSSLESS",
            }
        ],
        expanded=["tracks"],
    )
    settle(150)
    find_button = "var b=findFirst(root, function(o) {return o.chooserKind !== undefined && o.mediaId === 't1';}); "

    def read(body):
        return q(scene_js(find_button + body))

    read("b.openChooser(); return true;")
    settle(200)
    q("root.previewId = 'apple:preview'; root.previewDuration = 90000; root.previewStopMs = 90000")
    assert read("return b.chooserOffers.length;") == 7
    # Incompatible explicit audio and lyrics remain intact until confirmation.
    read("b.chooserPickAudio('both'); b.chooserToggle('lyrics_file'); return true;")
    settle(200)
    read("b.chooseProvider('p1'); return true;")
    assert read("return b.chooserProvider;") == "tidal"
    assert read("return b.chooserPendingSwitch !== null;")
    read("b.confirmProviderSwitch(); return true;")
    settle(200)
    assert read("return b.chooserProvider;") == "p1"
    assert read("return b.chooserAudio;") == "stereo"
    assert read("return b.chooserProviderPinned;")
    read("b.chooserPickTier('HIGH'); return true;")
    settle(200)
    read("b.chooseProvider('p2'); return true;")
    settle(200)
    assert read("return b.chooserTier;") == "HIGH"
    assert q("root.previewId") == "apple:preview"
    assert q("root.previewDuration") == 90000
    assert q("root.previewStopMs") == 90000
    # One expanded options owner at every width; wrapped names stay in bounds.
    for width, height in ((640, 600), (1100, 760), (1720, 980)):
        root.resize(width, height)
        settle(100)
        result = json.loads(
            read("""var p=findObject(root,'chooserPopover'); var pos=p.contentItem.mapToItem(root.contentItem,0,0);
            return JSON.stringify({w:p.width,h:p.height,x:pos.x-p.padding,y:pos.y-p.padding,ww:root.width,wh:root.height});""")
        )
        assert result["x"] >= 0 and result["x"] + result["w"] <= result["ww"] + 1, result
        assert result["y"] >= 0 and result["y"] + result["h"] <= result["wh"] + 1, result
    # Real keyboard activation on a provider row and Escape restoring the button.
    read(
        "var p=findObject(root,'chooserPopover'); var row=findFirst(p.contentItem,function(o){return o.providerId === 'p3';}); row.forceActiveFocus(); return true;"
    )
    QTest.keyClick(root, Qt.Key_Return)
    settle(200)
    assert read("return b.chooserProvider;") == "p3"
    QTest.keyClick(root, Qt.Key_Escape)
    settle(100)
    assert not read("return b.chooserOpen;")
    assert read("return b.activeFocus;")
    print("Chooser switches, confirmation, many offers, long names, keyboard and bounds passed")
    return 0


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(scenario())

import QtQuick
import "primitives" as Primitives

// Full-width preview control shaped like DownloadButton. Idle: ▶ + "PREVIEW
// ARTIST". Once playing it becomes a scrubber: the leading ▶/⏸ glyph toggles
// play/pause, and clicking or dragging the DotMatrix track seeks/scrubs the
// whole track (position readout on the right). One shared player, so only the
// active artist's bar shows the scrubber; the rest stay idle.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.fmtMs / host.ledPulse / host.previewDuration /
//   host.previewPosition / host.previewScrubbing / host.pvFrac / host.pvSt /
//   host.queueEdgeHeld / host.scrubPreviewVisual / host.seekPreview /
//   host.shimmerPhase / host.stopPreview / host.togglePreview
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: pbar
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property real btnBorderW: 1.5
  readonly property int btnPadH: 12             // label padding, left/right
  readonly property int btnPadV: 7              // label padding, top/bottom
  readonly property int btnRad: 8              // button corner radius
  readonly property real btnTrack: 0              // label letter-spacing
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color redCont: "#2a0e0c"
  readonly property color textLo: "#a8acb4"
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)

  property string pid: ""
  property string kind: "artist"
  property string label: "Preview Artist"
  readonly property string st: pbar.pid !== "" ? host.pvSt(pbar.kind, pbar.pid) : ""
  readonly property bool live: st === "playing" || st === "paused"
  readonly property real frac: host.pvFrac(pbar.kind, pbar.pid)
  // Inside a RollSwap the outline is the wrapper's pill, and drawing a
  // second one here would double every edge. The fill stays: it is what
  // makes the control read over artwork.
  property bool bare: false
  width: 140
  height: 30
  radius: btnRad
  clip: true
  // natural (content) size per the shared button rules, callers may
  // still set explicit width/height (the artist page's fixed bar does)
  implicitWidth: pbIdleRow.implicitWidth + btnPadH * 2
  implicitHeight: pbIdleRow.implicitHeight + btnPadV * 2
  color: st === "error" ? redCont : "transparent"
  border.width: bare ? 0 : btnBorderW
  border.color: st === "error" ? red : accentDim
  // consume clicks so the card-wide open-artist MouseArea (z:-1) never fires
  MouseArea {
    anchors.fill: parent
    onPressed: function (m) {
      m.accepted = true
    }
  }

  // IDLE / LOADING / ERROR, centered glyph + label (mirrors DownloadButton)
  Row {
    id: pbIdleRow
    anchors.centerIn: parent
    spacing: 7
    visible: !pbar.live
    Ico {
      visible: pbar.st !== "loading"
      name: pbar.st === "error" ? "close" : "play"
      color: pbar.st === "error" ? red : accent
      size: 13
      anchors.verticalCenter: parent.verticalCenter
    }
    Text {
      textFormat: Text.PlainText
      text: pbar.st === "loading" ? "[buffering]" : (pbar.st === "error" ? "PREVIEW FAILED" : pbar.label.toUpperCase())
      color: pbar.st === "error" ? red : accent
      font.family: pbar.st === "loading" ? mono : uiFont
      font.pixelSize: 11
      font.bold: true
      font.letterSpacing: btnTrack
      anchors.verticalCenter: parent.verticalCenter
      property real breathe: 1
      opacity: pbar.st === "loading" ? breathe : 1
      SequentialAnimation on breathe {
        running: pbar.st === "loading"
        loops: Animation.Infinite
        NumberAnimation {
          from: 1.0
          to: 0.3
          duration: 520
          easing.type: Easing.InOutSine
        }
        NumberAnimation {
          from: 0.3
          to: 1.0
          duration: 520
          easing.type: Easing.InOutSine
        }
      }
    }
  }
  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    visible: !pbar.live
    enabled: !pbar.live
    onClicked: host.togglePreview(pbar.kind, pbar.pid, 0)  // 0 = whole track (scrubbable)
  }

  // PLAYING / PAUSED, [⏵/⏸ toggle][DotMatrix scrub track][m:ss / m:ss]
  Item {
    anchors.fill: parent
    anchors.leftMargin: 8
    anchors.rightMargin: 10
    visible: pbar.live
    // Play/pause glyph, its own click zone so it never seeks.
    Ico {
      id: pbarGlyph
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      name: pbar.st === "playing" ? "pause" : "play"
      color: accent
      size: 13
      width: 18
      MouseArea {
        anchors.fill: parent
        anchors.margins: -4
        cursorShape: Qt.PointingHandCursor
        onClicked: function (m) {
          m.accepted = true
          host.togglePreview(pbar.kind, pbar.pid, 0)
        }
      }
    }
    // Stop, red ■ beside the ⏸ so play/pause and stop sit together;
    // red at rest so it stands out, brighter on hover.
    Ico {
      id: pbarStop
      anchors.left: pbarGlyph.right
      anchors.verticalCenter: parent.verticalCenter
      name: "stop"
      color: pbarStopMa.containsMouse ? "#ff7d76" : red
      size: 11
      MouseArea {
        id: pbarStopMa
        anchors.fill: parent
        anchors.margins: -5
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: function (m) {
          m.accepted = true
          host.stopPreview()
        }
      }
    }
    // Same reservation as the download button's readout, for the same
    // reason: the scrub track is anchored to this text's left edge, so
    // the minute rolling over to two digits mid-track would resize the
    // matrix and leave its columns stale for the settle interval. The
    // widest this track can read is the duration on both sides.
    TextMetrics {
      id: pbarTimeM
      font: pbarTime.font
      readonly property real widest: Math.max(host.previewDuration, host.previewPosition)
      text: host.fmtMs(widest) + " / " + host.fmtMs(widest)
    }
    Text {
      id: pbarTime
      textFormat: Text.PlainText
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      width: pbarTimeM.width
      horizontalAlignment: Text.AlignRight
      text: host.fmtMs(host.previewPosition) + " / " + host.fmtMs(host.previewDuration)
      color: textLo
      font.family: mono
      font.pixelSize: 10
    }
    // Scrub track, click seeks, drag scrubs. The DotMatrix fill follows
    // previewPosition, which seekPreview updates instantly for zero lag.
    Item {
      id: pbarTrack
      anchors.left: pbarStop.right
      anchors.leftMargin: 8
      anchors.right: pbarTime.left
      anchors.rightMargin: 8
      anchors.verticalCenter: parent.verticalCenter
      height: parent.height
      DotMatrix {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        rows: 4
        dot: 3
        gap: 2
        pct: pbar.frac * 100
        ledPulse: host.ledPulse
        shimmerPhase: host.shimmerPhase
        queueEdgeHeld: host.queueEdgeHeld
      }
      MouseArea {
        id: pbarScrub
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        preventStealing: true
        property bool scrubbing: false
        // Press/drag only move the fill; the single real seek fires
        // on release, so the backend seeks once and playback resumes
        // cleanly (no mid-gesture flush pop).
        function frac(x) {
          return width > 0 ? x / width : 0
        }
        onPressed: function (m) {
          m.accepted = true
          scrubbing = true
          host.previewScrubbing = true
          host.scrubPreviewVisual(frac(m.x))
        }
        onPositionChanged: function (m) {
          if (scrubbing)
            host.scrubPreviewVisual(frac(m.x))
        }
        onReleased: function (m) {
          if (scrubbing) {
            scrubbing = false
            host.previewScrubbing = false
            host.seekPreview(frac(m.x))
          }
        }
        onCanceled: {
          scrubbing = false
          host.previewScrubbing = false
        }
      }
    }
  }
}

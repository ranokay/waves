import QtQuick
import "../../primitives" as Primitives
import "../../primitives"

// Compact ASCII preview toggle for album track rows, where a per-row cover
// would just repeat the album art. Idle it's a tight mono "[>]"; on play it
// wipes open into the SAME DotMatrix the download buttons use (4 rows,
// column-major bottom-up, pulsing lead) and fills across the whole track.
// The live controls provide pause, stop and seeking. Loading shows a
// breathing "[buffering]"; error "[✕]".
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.fmtMs / host.ledPulse / host.previewDuration /
//   host.previewPosition / host.previewScrubbing / host.pvFrac / host.pvSt /
//   host.queueEdgeHeld / host.scrubPreviewVisual / host.seekPreview /
//   host.shimmerPhase / host.stopPreview / host.togglePreview
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Item {
  id: tp
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color textLo: "#a8acb4"

  property string kind: "track"
  property string pid: ""
  property string label: "Preview track"
  readonly property string st: tp.pid !== "" ? host.pvSt(tp.kind, tp.pid) : ""
  readonly property bool playing: tp.st === "playing"
  readonly property bool loading: tp.st === "loading"
  readonly property bool err: tp.st === "error"
  readonly property real pct: host.pvFrac(tp.kind, tp.pid) * 100
  // Live (playing or paused) expands into the row scrubber: pause / red
  // stop / seekable dot matrix / elapsed.
  readonly property bool live: tp.st === "playing" || tp.st === "paused"
  readonly property bool expanded: tp.live
  // Matrix geometry mirrors DownloadButton's running bar (rows 4, dot 3, gap 2).
  readonly property int matCols: 12
  readonly property real matW: matCols * 3 + (matCols - 1) * 2   // 58
  readonly property real collapsedW: 12

  implicitWidth: bracketRow.implicitWidth
  implicitHeight: 24

  // Underneath the live controls so their tap areas win while expanded.
  TapAction {
    objectName: "trackPreviewStart"
    anchors.fill: parent
    enabled: !tp.live && tp.pid !== ""
    accessibleLabel: tp.label
    onTriggered: host.togglePreview(tp.kind, tp.pid, 0)
  }
  Row {
    id: bracketRow
    anchors.verticalCenter: parent.verticalCenter
    spacing: 2
    Text {
      textFormat: Text.PlainText
      text: "["
      color: tp.err ? red : accentDim
      font.family: mono
      font.pixelSize: 13
      font.bold: true
      anchors.verticalCenter: parent.verticalCenter
    }
    // Morphing centre: the caret and the matrix crossfade while the box
    // width animates, so it reads as one control expanding / collapsing.
    Item {
      id: centre
      anchors.verticalCenter: parent.verticalCenter
      clip: true
      // Loading widens the box to fit "buffering", the surrounding
      // brackets make it read as "[buffering]" like the card labels.
      width: tp.expanded ? liveRow.implicitWidth : (tp.loading ? caret.implicitWidth + 2 : tp.collapsedW)
      height: 18   // 4*3 + 3*2
      Behavior on width {
        NumberAnimation {
          duration: 200
          easing.type: Easing.OutCubic
        }
      }
      // Standalone pulse value (never bound elsewhere) so animating it
      // can't clobber the caret's opacity binding; the caret only reads it
      // while loading, to breathe during the multi-second full-track resolve.
      property real loadPulse: 1
      SequentialAnimation on loadPulse {
        running: tp.loading
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
      Text {
        id: caret
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: tp.loading ? "buffering" : (tp.err ? "✕" : ">")
        color: tp.err ? red : accent
        font.family: mono
        font.pixelSize: 13
        font.bold: true
        opacity: tp.loading ? centre.loadPulse : (tp.expanded ? 0 : 1)
        Behavior on opacity {
          NumberAnimation {
            duration: 130
          }
        }
      }
      Row {
        id: liveRow
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        opacity: tp.expanded ? 1 : 0
        Behavior on opacity {
          NumberAnimation {
            duration: 130
          }
        }
        Icon {
          anchors.verticalCenter: parent.verticalCenter
          name: tp.playing ? "pause" : "play"
          color: accent
          size: 11
          TapAction {
            objectName: "trackPreviewToggle"
            anchors.fill: parent
            anchors.margins: -4
            enabled: tp.live
            accessibleLabel: tp.st === "playing" ? "Pause preview" : "Resume preview"
            onTriggered: function () {
              host.togglePreview(tp.kind, tp.pid, 0)
            }
          }
        }
        Icon {
          anchors.verticalCenter: parent.verticalCenter
          name: "stop"
          color: tpStopMa.containsMouse ? "#ff7d76" : red
          size: 11
          TapAction {
            id: tpStopMa
            objectName: "trackPreviewStop"
            anchors.fill: parent
            anchors.margins: -5
            enabled: tp.live
            hoverEnabled: enabled
            accessibleLabel: "Stop preview"
            onTriggered: function () {
              host.stopPreview()
            }
          }
        }
        Item {
          width: tp.matW
          height: 18
          anchors.verticalCenter: parent.verticalCenter
          DotMatrix {
            anchors.fill: parent
            rows: 4
            dot: 3
            gap: 2
            pct: tp.pct
            ledPulse: host.ledPulse
            shimmerPhase: host.shimmerPhase
            queueEdgeHeld: host.queueEdgeHeld
          }
          PreviewSeekArea {
            host: tp.host
            anchors.fill: parent
            enabled: tp.live
          }
        }
        Text {
          textFormat: Text.PlainText
          anchors.verticalCenter: parent.verticalCenter
          text: host.fmtMs(host.previewPosition) + " / " + host.fmtMs(host.previewDuration)
          color: textLo
          font.family: mono
          font.pixelSize: 10
        }
      }
    }
    Text {
      textFormat: Text.PlainText
      text: "]"
      color: tp.err ? red : accentDim
      font.family: mono
      font.pixelSize: 13
      font.bold: true
      anchors.verticalCenter: parent.verticalCenter
    }
  }
}

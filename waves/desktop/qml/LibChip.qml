import QtQuick
import "primitives" as Primitives

// One My Music strip chip: a dot, a label and the selected treatment --
// the shape both the Library section's views and a source group's
// categories render. The owner supplies the words and handles `picked`.
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: chip
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color textDim: "#6b6f78"
  readonly property color textLo: "#a8acb4"

  property string label: ""
  property bool on: false
  signal picked
  radius: 8
  implicitHeight: 30
  implicitWidth: chipRow.implicitWidth + 26
  color: chip.on ? accentCont : "transparent"
  border.color: chip.on ? accentDim : border1
  Row {
    id: chipRow
    anchors.centerIn: parent
    spacing: 7
    Rectangle {
      width: 6
      height: 6
      radius: 3
      anchors.verticalCenter: parent.verticalCenter
      color: chip.on ? accent : textDim
    }
    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      text: chip.label
      color: chip.on ? accent : textLo
      font.pixelSize: 13
    }
  }
  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: chip.picked()
  }
}

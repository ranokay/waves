import QtQuick

// Explicit-content mark, in the app's mono data voice.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  objectName: "explicitMark"
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — a copy of Main.qml's textLo, a step
  // lighter than the dim grey so the mark does not sink into the row
  // background at 14px.
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color textLo: "#a8acb4"
  radius: 3
  color: "transparent"
  border.color: textLo
  border.width: 1
  implicitWidth: 14
  implicitHeight: 14
  Text {
    anchors.centerIn: parent
    text: "E"
    color: textLo
    font.family: mono
    font.pixelSize: 9
    font.bold: true
  }
}

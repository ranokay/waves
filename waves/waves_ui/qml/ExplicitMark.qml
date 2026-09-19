import QtQuick

// Explicit-content mark, in the app's mono data voice.
// Split out of Main.qml (#315). The palette values are local copies of
// Main.qml's static literals — the SettingsPage.qml convention; keep them
// in step if the palette changes.
Rectangle {
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color textDim: "#6b6f78"
  radius: 3
  color: "transparent"
  border.color: textDim
  border.width: 1
  implicitWidth: 14
  implicitHeight: 14
  Text {
    anchors.centerIn: parent
    text: "E"
    color: textDim
    font.family: mono
    font.pixelSize: 9
    font.bold: true
  }
}

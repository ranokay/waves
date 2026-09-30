import QtQuick
import "primitives" as Primitives

// Explicit-content mark, in the app's mono data voice.
// The palette values are local copies of Main.qml's static literals, except textDim which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — textDim binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color textDim: Primitives.Palette.textDim
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

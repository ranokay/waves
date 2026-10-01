import QtQuick

// Playlist-folder tile: folders draw their own glyph, they
// have no artwork.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color surface3: "#1d2128"   // art bg / unlit meter / inset

  width: 44
  height: 44
  radius: 6
  color: surface3
  border.color: border1
  border.width: 1
  Item {
    anchors.centerIn: parent
    width: 22
    height: 17
    Rectangle {
      width: 9
      height: 4
      radius: 1
      color: "transparent"
      border.width: 1.2
      border.color: accentDim
    }
    Rectangle {
      y: 3
      width: 22
      height: 14
      radius: 2
      color: "transparent"
      border.width: 1.2
      border.color: accentDim
    }
  }
}

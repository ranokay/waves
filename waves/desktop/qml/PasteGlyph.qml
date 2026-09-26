import QtQuick
import "primitives" as Primitives

// Clipboard glyph that "decrypt-fills" on paste. Shared by the search bar and
// the login redirect field so both get the identical paste affordance.
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: pg
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentContTx: "#86ffaa"   // text on accent container
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color surface3: "#1d2128"   // art bg / unlit meter / inset

  signal clicked
  function play() {
    decAnim.restart()
  }
  implicitWidth: 30
  implicitHeight: 30
  radius: 7
  color: pgMa.containsMouse ? accentCont : surface3
  border.color: pgMa.containsMouse ? accentDim : border1
  property real fillT: 0          // 0..1 decrypt-fill level
  property real fillOpacity: 0

  Rectangle {            // clipboard body (clips the rising fill)
    id: clipBody
    anchors.centerIn: parent
    anchors.verticalCenterOffset: 1
    width: 14
    height: 16
    radius: 2
    clip: true
    color: "transparent"
    border.color: accent
    border.width: 1.4
    Rectangle {        // rising decrypt fill
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      height: parent.height * pg.fillT
      color: accent
      opacity: pg.fillOpacity
    }
    Rectangle {
      x: 3
      y: 4
      width: 8
      height: 1.4
      color: accent
      opacity: pg.fillT >= (1 - 4 / clipBody.height) ? 1 : 0.4
    }
    Rectangle {
      x: 3
      y: 8
      width: 8
      height: 1.4
      color: accent
      opacity: pg.fillT >= (1 - 8 / clipBody.height) ? 1 : 0.4
    }
    Rectangle {
      x: 3
      y: 12
      width: 6
      height: 1.4
      color: accent
      opacity: pg.fillT >= (1 - 12 / clipBody.height) ? 1 : 0.4
    }
    Rectangle {        // bright scan line riding the top of the fill
      anchors.left: parent.left
      anchors.right: parent.right
      y: Math.max(0, parent.height * (1 - pg.fillT) - 1)
      height: 2
      color: accentContTx
      visible: pg.fillT > 0.001 && pg.fillT < 0.999
    }
  }
  Rectangle {            // clipboard tab/clamp
    anchors.horizontalCenter: clipBody.horizontalCenter
    y: clipBody.y - 2
    width: 7
    height: 4
    radius: 1
    color: pg.color
    border.color: accent
    border.width: 1.4
  }
  SequentialAnimation {
    id: decAnim
    PropertyAction {
      target: pg
      property: "fillOpacity"
      value: 0.32
    }
    NumberAnimation {
      target: pg
      property: "fillT"
      from: 0
      to: 1
      duration: 430
      easing.type: Easing.OutCubic
    }
    NumberAnimation {
      target: pg
      property: "fillOpacity"
      from: 0.32
      to: 0
      duration: 240
    }
    PropertyAction {
      target: pg
      property: "fillT"
      value: 0
    }
  }
  MouseArea {
    id: pgMa
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: pg.clicked()
  }
}

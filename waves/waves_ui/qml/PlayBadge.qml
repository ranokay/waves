import QtQuick

// Video thumbnail: 16:9-ish art with a scanline play strip.
// The one video-play affordance: a green data-strip along the bottom edge
// of the art with an ink triangle and PLAY label, like a terminal status
// bar. `lit` brightens and thickens it while the row/thumb is hovered.
// Fills its parent (the thumb): the strip anchors itself to the bottom.
// Play affordance on video artwork: the least ink that still reads. A
// shadow rises out of the bottom edge so the mark stays legible over any
// frame, and the mark is a small triangle in the corner. This replaces a
// full-width green strip with "PLAY" set into it, which ate a quarter of
// an 88x50 thumb; the picture is the point, the more so now that resting
// on one plays it. `radius` follows the art the badge sits on (6 on the
// rounded browse thumbs, 0 on the square track-row ones).
Item {
  id: pb
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentSoft: "#9dffbe"   // CRT flash / phosphor highlight
  property bool lit: false
  property real radius: 6
  anchors.fill: parent
  Rectangle {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    height: Math.round(parent.height * 0.42)
    radius: pb.radius
    // Eased, and with no band squaring off the top edge: the scrim is
    // fully transparent up there, so its rounded top corners never
    // showed anyway, while the band's own step from transparent to
    // #33 drew a hard line straight across a grid-sized thumbnail.
    gradient: Gradient {
      GradientStop {
        position: 0.0
        color: "#0006090c"
      }
      GradientStop {
        position: 0.45
        color: "#4406090c"
      }
      GradientStop {
        position: 1.0
        color: pb.lit ? "#dd06090c" : "#cc06090c"
      }
    }
  }
  Canvas {
    anchors.left: parent.left
    anchors.bottom: parent.bottom
    anchors.leftMargin: 6
    anchors.bottomMargin: 6
    width: pb.lit ? 9 : 8
    height: pb.lit ? 10 : 9
    readonly property color ink: pb.lit ? accentSoft : accent
    // Repaint on every input to the paint, none of which Canvas
    // watches by itself.
    onInkChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
      var c = getContext("2d")
      c.reset()
      c.fillStyle = "" + ink
      c.beginPath()
      c.moveTo(0, 0)
      c.lineTo(0, height)
      c.lineTo(width, height / 2)
      c.closePath()
      c.fill()
    }
  }
}

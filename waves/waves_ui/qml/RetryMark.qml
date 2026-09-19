import QtQuick

// Vector retry mark: two opposing arcs with arrowheads (sync-twin,
// diagonal), chosen in the vector retry lab. Drawn geometry instead of
// a font glyph so it renders identically on every OS: JetBrains Mono's
// only retry-shaped characters (↩ ↞) read thin and off-centre next to
// the heavy ↓ ✓ ▶, and the classic circular arrows (↺ ↻ ⟳) are missing
// from the font entirely.
// Split out of Main.qml (#315 slice 2). The palette value is a local
// copy of Main.qml's static literal — the SettingsPage.qml convention.

Item {
  id: rm
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color red: "#ff5a52"   // failed / peak / heart

  property color color: red
  property real box: 16
  implicitWidth: box
  implicitHeight: box
  onColorChanged: rmCanvas.requestPaint()
  Canvas {
    id: rmCanvas
    anchors.fill: parent
    antialiasing: true
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      var b = rm.box, cx = width / 2, cy = height / 2, r = b * 0.335
      ctx.strokeStyle = rm.color
      ctx.fillStyle = rm.color
      ctx.lineWidth = Math.max(1.5, b * 0.115)
      ctx.lineCap = "round"
      ctx.lineJoin = "round"
      ctx.translate(cx, cy)
      ctx.rotate(-Math.PI / 4)
      ctx.translate(-cx, -cy)
      function head(x, y, ang, s) {
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(ang)
        ctx.beginPath()
        ctx.moveTo(s * 0.95, 0)
        ctx.lineTo(-s * 0.55, -s * 0.62)
        ctx.lineTo(-s * 0.55, s * 0.62)
        ctx.closePath()
        ctx.fill()
        ctx.restore()
      }
      var g = (Math.PI - Math.PI * 0.70) / 2
      var t0 = -Math.PI + g, t1 = -g
      ctx.beginPath()
      ctx.arc(cx, cy, r, t0, t1, false)
      ctx.stroke()
      head(cx + r * Math.cos(t1), cy + r * Math.sin(t1), t1 + Math.PI / 2, b * 0.22)
      var b0 = g, b1 = Math.PI - g
      ctx.beginPath()
      ctx.arc(cx, cy, r, b0, b1, false)
      ctx.stroke()
      head(cx + r * Math.cos(b1), cy + r * Math.sin(b1), b1 + Math.PI / 2, b * 0.22)
    }
  }
}

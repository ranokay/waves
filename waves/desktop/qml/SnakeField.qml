import QtQuick
import "primitives" as Primitives

// A small snake circling the loading label, used as the waiting surface
// of the peek card. It laps a ring laid around the plate, eating the
// bites dropped on the path and growing a little with each one; only a
// wait long enough to fill most of the ring (minutes, i.e. genuinely bad
// internet) makes the run start over. The body is just (head, length)
// along the ring, so the card resizing mid-grow re-lays the path without
// ever scattering segments. The clock only runs while the field is both
// visible and armed, so a closed peek costs nothing.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Item {
  id: sf
  property bool running: false
  property real cell: 9
  property real gap: 12
  property real plateW: 0
  property real plateH: 0
  // Pixel top-left corners of the ring cells, walked clockwise.
  property var ring: []
  property int head: 0
  property int len: 5
  property int food: -1
  readonly property color accent: Primitives.Palette.accent
  readonly property color goldDim: "#b07d18"

  function _buildRing() {
    var w = plateW + gap * 2 + cell
    var h = plateH + gap * 2 + cell
    if (plateW <= 0 || plateH <= 0 || width < w + cell || height < h + cell) {
      ring = []
      cv.requestPaint()
      return
    }
    var x0 = (width - w) / 2
    var y0 = (height - h) / 2
    var nx = Math.max(4, Math.round(w / cell))
    var ny = Math.max(3, Math.round(h / cell))
    var sx = w / nx
    var sy = h / ny
    var r = []
    var i
    for (i = 0; i < nx; i++)
      r.push({
        x: x0 + i * sx,
        y: y0
      })
    for (i = 1; i < ny; i++)
      r.push({
        x: x0 + (nx - 1) * sx,
        y: y0 + i * sy
      })
    for (i = nx - 2; i >= 0; i--)
      r.push({
        x: x0 + i * sx,
        y: y0 + (ny - 1) * sy
      })
    for (i = ny - 2; i >= 1; i--)
      r.push({
        x: x0,
        y: y0 + i * sy
      })
    var wasEmpty = ring.length === 0
    ring = r
    // The card opens smaller than the ring needs and grows into it,
    // so the run truly starts here, on the frame the ring first fits
    // (a reset against the empty ring parked food at -1 for good).
    if (wasEmpty && running) {
      reset()
      return
    }
    if (head >= r.length)
      head = head % r.length
    if (len > r.length - 4)
      len = Math.max(3, r.length - 4)
    if (food < 0 || food >= r.length)
      _placeFood()
    cv.requestPaint()
  }
  function _occupied(idx) {
    var n = ring.length
    for (var i = 0; i < len; i++)
      if ((head - i + n * 2) % n === idx)
        return true
    return false
  }
  function _placeFood() {
    var n = ring.length
    if (n === 0) {
      food = -1
      return
    }
    // Drop the bite somewhere ahead on the lap, never on the snake.
    for (var t = 0; t < 30; t++) {
      var idx = (head + 3 + Math.floor(Math.random() * Math.max(1, n - len - 4))) % n
      if (!_occupied(idx)) {
        food = idx
        return
      }
    }
    food = -1
  }
  function reset() {
    len = 5
    var n = ring.length
    if (n === 0) {
      food = -1
      cv.requestPaint()
      return
    }
    // Random start, so two peeks in a row are not the same run.
    head = Math.floor(Math.random() * n)
    // The first bite lands just ahead of the head (3 to 6 cells, well
    // under a second away), so even a quick load shows the snake eat
    // at least once. Clamped clear of the tail on a tiny ring.
    var off = 3 + Math.floor(Math.random() * 4)
    if (off > n - len - 1)
      off = Math.max(1, n - len - 1)
    food = (head + off) % n
    cv.requestPaint()
  }
  function step() {
    var n = ring.length
    if (n === 0)
      return
    head = (head + 1) % n
    if (head === food) {
      len += 1
      // Filling most of the lap takes minutes of eating: shed the
      // weight and keep going rather than catching the tail.
      if (len >= n - 4)
        len = 5
      _placeFood()
    }
    cv.requestPaint()
  }
  onRunningChanged: if (running) {
    _buildRing()
    reset()
  }
  onWidthChanged: _buildRing()
  onHeightChanged: _buildRing()
  onPlateWChanged: _buildRing()
  onPlateHChanged: _buildRing()
  Timer {
    running: sf.running && sf.visible
    interval: 110
    repeat: true
    onTriggered: sf.step()
  }
  Canvas {
    id: cv
    anchors.fill: parent
    onPaint: {
      var c = getContext("2d")
      c.reset()
      var n = sf.ring.length
      if (n === 0)
        return
      var s = sf.cell
      var pad = Math.max(1, Math.round(s * 0.18))
      if (sf.food >= 0 && sf.food < n) {
        var f = sf.ring[sf.food]
        c.fillStyle = "" + sf.goldDim
        c.fillRect(f.x + pad, f.y + pad, s - pad * 2, s - pad * 2)
      }
      for (var i = 0; i < sf.len; i++) {
        var seg = sf.ring[(sf.head - i + n * 2) % n];
        // Head brightest, fading down the tail: reads as motion
        // even in a still frame.
        var a = Math.max(0.14, 0.55 - i * 0.55 / Math.max(1, sf.len))
        c.fillStyle = "" + Qt.alpha(sf.accent, a)
        c.fillRect(seg.x + pad, seg.y + pad, s - pad * 2, s - pad * 2)
      }
    }
  }
}

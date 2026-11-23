import QtQuick
import "../../primitives" as Primitives

// Shared preview scrub gesture: drag updates the display, release seeks once.
// Arrow keys and accessibility increment actions move by five seconds.
MouseArea {
  id: seekArea
  objectName: "previewSeekArea"
  required property var host
  property bool scrubbing: false
  readonly property real value: host.previewPosition
  readonly property real minimumValue: 0
  readonly property real maximumValue: host.previewDuration
  readonly property real stepSize: 5000
  activeFocusOnTab: visible && enabled
  cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
  preventStealing: true
  Accessible.role: Accessible.Slider
  Accessible.name: "Preview position"
  Accessible.description: host.fmtMs(value) + " of " + host.fmtMs(maximumValue)
  Accessible.onIncreaseAction: move(5)
  Accessible.onDecreaseAction: move(-5)

  function frac(x) {
    return width > 0 ? Math.max(0, Math.min(1, x / width)) : 0
  }
  function move(seconds) {
    if (enabled && maximumValue > 0)
      host.seekPreview(Math.max(0, Math.min(1, (value + seconds * 1000) / maximumValue)))
  }
  Keys.onPressed: function (event) {
    if (event.key === Qt.Key_Left || event.key === Qt.Key_Right) {
      move(event.key === Qt.Key_Left ? -5 : 5)
      event.accepted = true
    } else if (event.key === Qt.Key_Home || event.key === Qt.Key_End) {
      host.seekPreview(event.key === Qt.Key_Home ? 0 : 1)
      event.accepted = true
    }
  }
  onPressed: function (mouse) {
    mouse.accepted = true
    scrubbing = true
    host.previewScrubbing = true
    host.scrubPreviewVisual(frac(mouse.x))
  }
  onPositionChanged: function (mouse) {
    if (scrubbing)
      host.scrubPreviewVisual(frac(mouse.x))
  }
  onReleased: function (mouse) {
    if (scrubbing) {
      scrubbing = false
      host.previewScrubbing = false
      host.seekPreview(frac(mouse.x))
    }
  }
  onCanceled: {
    scrubbing = false
    host.previewScrubbing = false
  }
  Rectangle {
    anchors.fill: parent
    color: "transparent"
    radius: 3
    border.color: Primitives.Palette.accent
    border.width: 2
    visible: seekArea.activeFocus
  }
}

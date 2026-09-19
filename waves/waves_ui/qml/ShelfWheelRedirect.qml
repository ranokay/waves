import QtQuick

// A horizontal shelf (ListView) otherwise swallows vertical wheel/trackpad
// scroll to move itself sideways, trapping the enclosing page: on a landing
// or genre page that is nothing but shelves, the user can barely scroll
// down. Dropping one of these on a shelf redirects vertical-dominant wheel
// to the page while leaving horizontal-dominant wheel for the shelf's own
// flick, so the row still scrolls sideways with a trackpad swipe.
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
WheelHandler {

  property Flickable pane   // the vertical page to drive
  property var shelf: parent  // the horizontal shelf this rides on (a ListView)
  // Both axes are driven explicitly (and the event always accepted) so
  // behaviour never depends on wheel fall-through between the handler and
  // the Flickable: vertical wheel scrolls the page, horizontal wheel (a
  // trackpad sideways swipe) scrolls the shelf itself.
  onWheel: function (ev) {
    if (Math.abs(ev.angleDelta.y) >= Math.abs(ev.angleDelta.x)) {
      if (pane) {
        var maxY = Math.max(0, pane.contentHeight - pane.height)
        pane.contentY = Math.max(0, Math.min(maxY, pane.contentY - ev.angleDelta.y))
      }
    } else if (shelf) {
      var maxX = Math.max(0, shelf.contentWidth - shelf.width)
      shelf.contentX = Math.max(0, Math.min(maxX, shelf.contentX - ev.angleDelta.x))
    }
    ev.accepted = true
  }
}

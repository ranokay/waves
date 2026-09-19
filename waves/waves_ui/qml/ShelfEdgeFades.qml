import QtQuick

// The horizontal counterpart of BackToTop's LIP edge fades: a short dense
// darkening at the left and right of a shelf's viewport so cards fade in
// and out of frame instead of being cut off hard at the shelf edge. Same
// gating rules as the vertical pair: fully transparent at the very start
// (contentX 0), ramping in over the first fadeW pixels of travel; the
// right fade lifts as the end of the shelf arrives; a shelf too short to
// scroll shows no fades at all. Declared inside the shelf it dresses: a
// Flickable reparents declared children onto its contentItem (they would
// scroll away with the cards), so onCompleted walks up to the shelf and
// hoists the overlay back onto it, viewport-fixed above the delegates.
// The gradient runs top-to-bottom, so each band is built sideways and
// rotated about its center: -90 points the dense edge left, 90 right.
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Item {
  id: sef

  property Flickable shelf: null
  readonly property real fadeW: 34
  anchors.fill: shelf
  z: 10
  Component.onCompleted: {
    var p = parent
    while (p && p.contentX === undefined)
      p = p.parent
    // Parent first, shelf second: anchors.fill binds to shelf, and it
    // must never see a shelf that is not yet the parent (warning).
    if (p) {
      sef.parent = p
      sef.shelf = p
    }
  }
  Rectangle {
    width: sef.height
    height: sef.fadeW
    x: (sef.fadeW - sef.height) / 2
    y: (sef.height - sef.fadeW) / 2
    rotation: -90
    visible: sef.shelf !== null && opacity > 0
    opacity: sef.shelf ? Math.min(1, Math.max(0, sef.shelf.contentX) / sef.fadeW) : 0
    gradient: Gradient {
      GradientStop {
        position: 0
        color: "#0d0f12"
      }
      GradientStop {
        position: 0.25
        color: Qt.alpha("#0d0f12", 0.82)
      }
      GradientStop {
        position: 0.6
        color: Qt.alpha("#0d0f12", 0.28)
      }
      GradientStop {
        position: 1
        color: Qt.alpha("#0d0f12", 0)
      }
    }
  }
  Rectangle {
    width: sef.height
    height: sef.fadeW
    x: sef.width - (sef.fadeW + sef.height) / 2
    y: (sef.height - sef.fadeW) / 2
    rotation: 90
    visible: sef.shelf !== null && opacity > 0
    opacity: sef.shelf ? Math.min(1, Math.max(0, sef.shelf.contentWidth - sef.shelf.width - sef.shelf.contentX) / sef.fadeW) : 0
    gradient: Gradient {
      GradientStop {
        position: 0
        color: "#0d0f12"
      }
      GradientStop {
        position: 0.25
        color: Qt.alpha("#0d0f12", 0.82)
      }
      GradientStop {
        position: 0.6
        color: Qt.alpha("#0d0f12", 0.28)
      }
      GradientStop {
        position: 1
        color: Qt.alpha("#0d0f12", 0)
      }
    }
  }
}

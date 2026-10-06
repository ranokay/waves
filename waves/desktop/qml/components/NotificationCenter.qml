import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../primitives" as Primitives
import "../primitives"

// The persistent half of the notification center: every retained notification
// (newest update first), refreshed when it opens and on every change while it
// stays open, with the same card the toasts use. Active issues are dismissible
// here; resolved history can be cleared.
// The palette values are local copies of Main.qml's static literals, except accent and textDim which bind to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Drawer {
  id: notificationCenter
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent and textDim bind to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color line1: "#22262d"   // row dividers
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color textDim: Primitives.Palette.textDim
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  required property var host
  edge: Qt.RightEdge
  height: host.height
  width: Math.max(420, Math.min(host.width - 80, 560))
  background: Rectangle {
    color: notificationCenter.surface
    border.color: notificationCenter.line1
  }

  property var items: []
  readonly property int activeCount: {
    var count = 0
    for (var i = 0; i < notificationCenter.items.length; i++) {
      if (String(notificationCenter.items[i].lifecycle) === "active")
        count++
    }
    return count
  }

  function refresh() {
    items = waves.notificationHistory()
  }

  onOpenedChanged: {
    if (opened)
      refresh()
  }

  Connections {
    target: waves
    function onNotificationsChanged() {
      if (notificationCenter.opened)
        notificationCenter.refresh()
    }
  }

  ColumnLayout {
    anchors.fill: parent
    anchors.margins: 16
    spacing: 12
    RowLayout {
      Layout.fillWidth: true
      spacing: 10
      Text {
        textFormat: Text.PlainText
        text: "Notifications"
        color: notificationCenter.textHi
        font.pixelSize: 16
        font.bold: true
      }
      Text {
        textFormat: Text.PlainText
        text: notificationCenter.items.length + " kept" + (notificationCenter.activeCount > 0 ? " · " + notificationCenter.activeCount + " active" : "")
        visible: notificationCenter.items.length > 0
        color: notificationCenter.textDim
        font.pixelSize: 11
      }
      Item {
        Layout.fillWidth: true
      }
      ActionButton {
        objectName: "notificationClear"
        visible: notificationCenter.items.length > 0
        compact: true
        label: "CLEAR"
        accessibleLabel: "Clear resolved notification history"
        onClicked: waves.clearNotificationHistory()
      }
      ActionButton {
        id: centerCloseBtn
        icon: "close"
        accessibleLabel: "Close notifications"
        onClicked: notificationCenter.close()
      }
    }
    Text {
      Layout.fillWidth: true
      visible: notificationCenter.items.length === 0
      textFormat: Text.PlainText
      text: "Nothing here yet. Downloads, warnings and errors appear here; active issues stay until they are resolved or dismissed."
      color: notificationCenter.textDim
      font.pixelSize: 12
      wrapMode: Text.WordWrap
      lineHeight: 1.2
    }
    ListView {
      id: centerList
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      spacing: 8
      model: notificationCenter.items
      delegate: NotificationCard {
        required property var modelData
        width: centerList.width
        entry: modelData
        onActionRequested: function (identity, action) {
          waves.eventAction(identity, action)
        }
        onCopyRequested: function (identity) {
          waves.copyEventDiagnostics(identity)
        }
        onReportRequested: function (identity) {
          waves.reportEventIssue(identity)
        }
        onDismissRequested: function (identity) {
          waves.dismissEvent(identity)
        }
      }
    }
  }
}

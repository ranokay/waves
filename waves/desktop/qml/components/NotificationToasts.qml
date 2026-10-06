import QtQuick
import "../primitives" as Primitives
import "../primitives"

// The transient half of the notification center: the live toast stack.
// It listens to the bridge's applicationEvent signal, shows at most three
// notices, merges nearby download completions into one aggregate, updates a
// repeated issue in place (its count rides the occurrences field), pauses each
// notice's dismissal while the pointer or keyboard focus rests on it, and sends
// anything over the limit, plus every resolved notice, to the persistent center.
// The palette values are local copies of Main.qml's static literals, except accent and textDim which bind to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Item {
  id: notificationToasts
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent and textDim bind to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color textDim: Primitives.Palette.textDim
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  required property var host
  signal openCenterRequested

  readonly property int maxVisible: 3
  readonly property string completionKey: "completions"
  // Re-read on the pref's changed signal; the binding alone cannot see an
  // edit (wavesPref is a slot call, not a notifying property).
  property bool motion: waves.wavesPref("notification_motion") !== false
  Connections {
    target: waves
    function onNotificationMotionChanged() {
      notificationToasts.motion = waves.wavesPref("notification_motion") !== false
    }
  }
  // Notices the three-visible limit kept out of the stack; the pill above the
  // stack carries the count and opens the center. Reset when the center opens.
  property int overflow: 0
  // The completion aggregate's accumulated lines; it lives beside the model
  // (ListModel roles cannot hold a mutable JS array) and resets with the row.
  property var completionLines: []

  function lifetimeFor(severity) {
    if (severity === "error")
      return 0
    // sticky until dismissed or resolved
    if (severity === "warning")
      return 8000
    return 4000
  }

  function isCompletion(payload) {
    return String(payload.domain) === "download" && String(payload.code) === "completed" && String(payload.severity) === "success"
  }

  function indexOfKey(key) {
    for (var i = 0; i < toastModel.count; i++) {
      if (String(toastModel.get(i).key) === key)
        return i
    }
    return -1
  }

  function visibleKeys() {
    var keys = []
    for (var i = 0; i < toastModel.count; i++)
      keys.push(String(toastModel.get(i).key))
    return keys
  }

  function toastCount() {
    return toastModel.count
  }

  function toastJson(index) {
    if (index < 0 || index >= toastModel.count)
      return ""
    return JSON.stringify(toastModel.get(index).entry)
  }

  function removeKey(key) {
    var index = indexOfKey(key)
    if (index >= 0)
      toastModel.remove(index)
    if (key === completionKey)
      completionLines = []
  }

  function beginLeave(key) {
    var index = indexOfKey(key)
    if (index < 0)
      return
    var item = toastRepeater.itemAt(index)
    if (item !== null && notificationToasts.motion) {
      item.leaving = true
      return
    }
    toastModel.remove(index)
  }

  function clearOverflow() {
    overflow = 0
  }

  function dismissKey(key) {
    if (key === completionKey) {
      beginLeave(key)
      return
    }
    waves.dismissEvent(key)
  }

  function mergeCompletion(payload) {
    var line = String(payload.summary || "Finished a download")
    var lines = completionLines.slice()
    lines.push(line)
    completionLines = lines
    var shown = lines.slice(0, 12)
    if (lines.length > 12)
      shown.push("…and " + (lines.length - 12) + " more in the notification center")
    var entry = {
      id: completionKey,
      severity: "success",
      title: lines.length === 1 ? line : "Finished " + lines.length + " downloads",
      summary: "",
      details: lines.length === 1 ? [] : shown,
      lifecycle: "active",
      actions: [],
      occurrences: 1
    }
    var index = indexOfKey(completionKey)
    if (index >= 0) {
      toastModel.setProperty(index, "entry", entry)
      return
    }
    if (toastModel.count >= maxVisible) {
      overflow += 1
      return
    }
    toastModel.append({
      key: completionKey,
      entry: entry,
      dismissible: false,
      lifetime: 4000
    })
  }

  function record(payload) {
    var key = String(payload.id || "")
    if (key === "")
      return
    if (isCompletion(payload)) {
      if (waves.wavesPref("notify_completion_toasts") === false)
        return
      mergeCompletion(payload)
      return
    }
    var index = indexOfKey(key)
    if (String(payload.lifecycle || "") !== "active") {
      if (index >= 0)
        beginLeave(key)
      return
    }
    if (index >= 0) {
      // The same identity came back (an updated count or summary): refresh in
      // place and restart its dismissal window.
      toastModel.setProperty(index, "entry", payload)
      return
    }
    if (toastModel.count >= maxVisible) {
      overflow += 1
      return
    }
    toastModel.append({
      key: key,
      entry: payload,
      dismissible: true,
      lifetime: lifetimeFor(String(payload.severity || ""))
    })
  }

  Connections {
    target: waves
    function onApplicationEvent(payload) {
      notificationToasts.record(payload)
    }
  }

  ListModel {
    id: toastModel
  }

  Column {
    id: toastStack
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    spacing: 8
    Rectangle {
      id: overflowPill
      objectName: "notificationOverflow"
      visible: notificationToasts.overflow > 0
      implicitWidth: overflowText.implicitWidth + 20
      implicitHeight: overflowText.implicitHeight + 10
      radius: 9
      color: notificationToasts.accentCont
      border.width: 1
      border.color: notificationToasts.accentDim
      Text {
        id: overflowText
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: "+" + notificationToasts.overflow + " MORE"
        color: notificationToasts.accent
        font.family: notificationToasts.mono
        font.pixelSize: 10
        font.bold: true
        font.letterSpacing: 0.8
      }
      TapAction {
        objectName: "notificationOverflowTap"
        anchors.fill: parent
        accessibleLabel: notificationToasts.overflow + (notificationToasts.overflow === 1 ? " more notification" : " more notifications") + " in the notification center"
        focusRadius: 9
        onTriggered: notificationToasts.openCenterRequested()
      }
    }
    Repeater {
      id: toastRepeater
      model: toastModel
      delegate: Item {
        id: toast
        required property int index
        required property string key
        required property var entry
        required property bool dismissible
        required property int lifetime
        readonly property bool completion: key === notificationToasts.completionKey
        // A notice waiting its dismissal window out. Sticky errors (lifetime
        // 0) never start one; the timer leaves them alone. The window is armed
        // in Component.onCompleted, because onEntryChanged may fire while the
        // required properties are still being injected (lifetime not yet set).
        property real msLeft: 0
        // Pause on hover or while keyboard focus rests anywhere in the card.
        property bool paused: hover.hovered || toast.focusWithin
        readonly property bool focusWithin: {
          var item = toast.Window.window ? toast.Window.window.activeFocusItem : null
          while (item) {
            if (item === toast)
              return true
            item = item.parent
          }
          return false
        }
        property bool leaving: false
        property bool shown: false
        implicitWidth: card.implicitWidth
        implicitHeight: card.implicitHeight
        opacity: shown ? (leaving ? 0 : 1) : 0
        Behavior on opacity {
          enabled: notificationToasts.motion
          NumberAnimation {
            duration: 160
          }
        }
        Component.onCompleted: {
          msLeft = lifetime
          shown = true
        }
        onEntryChanged: toast.msLeft = toast.lifetime
        onLeavingChanged: {
          if (!leaving)
            return
          if (notificationToasts.motion)
            leaveWait.start()
          else
            notificationToasts.removeKey(toast.key)
        }
        HoverHandler {
          id: hover
        }
        Timer {
          id: tick
          interval: 100
          repeat: true
          running: toast.lifetime > 0 && !toast.paused && !toast.leaving
          onTriggered: {
            toast.msLeft -= tick.interval
            if (toast.msLeft <= 0)
              notificationToasts.beginLeave(toast.key)
          }
        }
        Timer {
          id: leaveWait
          interval: 170
          onTriggered: notificationToasts.removeKey(toast.key)
        }
        NotificationCard {
          id: card
          width: parent.width
          entry: toast.entry
          dismissible: toast.dismissible
          backendEntry: !toast.completion
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
            notificationToasts.dismissKey(identity)
          }
        }
      }
    }
  }
}

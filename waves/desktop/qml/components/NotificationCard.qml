import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../primitives" as Primitives
import "../primitives"

// One notification, shared by the toast stack and the persistent center:
// severity, plain summary, the event's allowlisted actions, and an expandable
// detail with the safe details, the redacted advanced trace, and the
// copy/report affordances. The card renders; its host owns timing and dismissal.
// The palette values are local copies of Main.qml's static literals, except accent and textDim which bind to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: ncard
  objectName: "notificationCard"
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent and textDim bind to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color cyan: "#56c8d8"   // HIGH tier + queued
  readonly property color gold: "#ffb01f"   // HI-RES / VIDEO tier + meter mid band
  readonly property color green: "#3ef08a"   // LOSSLESS tier + done state
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color surface0: "#121418"   // topbar / statusbar / expand panel
  readonly property color surface2: "#191c22"   // hover / nested
  readonly property color textDim: Primitives.Palette.textDim
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  // The redacted event payload (or a synthesized completion aggregate).
  property var entry: ({})
  // Detail expansion is owned by the host so one card can be reused in both
  // the transient stack and the center's list.
  property bool expanded: false
  // Completion aggregates have no backend identity to dismiss.
  property bool dismissible: true
  // A synthesized aggregate (merged completions) has no retained entry behind
  // it: copy-diagnostics and report would resolve nothing, so they hide.
  property bool backendEntry: true

  signal actionRequested(string identity, string action)
  signal copyRequested(string identity)
  signal reportRequested(string identity)
  signal dismissRequested(string identity)

  readonly property string identity: String(ncard.entry.id || "")
  readonly property string severity: String(ncard.entry.severity || "info")
  readonly property bool live: String(ncard.entry.lifecycle || "") === "active"
  readonly property int occurrences: Math.max(1, Number(ncard.entry.occurrences || 1))
  readonly property color severityColor: ncard.severity === "success" ? ncard.green : ncard.severity === "warning" ? ncard.gold : ncard.severity === "error" ? ncard.red : ncard.cyan
  readonly property string severityWord: ncard.severity === "success" ? "Success" : ncard.severity === "warning" ? "Warning" : ncard.severity === "error" ? "Error" : "Info"
  readonly property var detailLines: ncard.entry.details || []
  readonly property string diagnosticsText: String(ncard.entry.diagnostics || "")
  readonly property bool hasDetails: ncard.detailLines.length > 0 || ncard.diagnosticsText !== ""
  // The redacted copy affordance lives in the detail; the allowlisted action
  // of the same name would only duplicate it.
  readonly property var actionList: {
    var values = ncard.entry.actions || []
    var out = []
    for (var i = 0; i < values.length; i++) {
      if (String(values[i]) !== "copy_diagnostics")
        out.push(String(values[i]))
    }
    return out
  }
  property bool advanced: false

  function actionLabel(action) {
    if (action === "open_settings")
      return "OPEN SETTINGS"
    if (action === "open_logs")
      return "OPEN LOGS"
    if (action === "reconnect")
      return "RECONNECT"
    if (action === "retry_job")
      return "RETRY"
    return action.replace(/_/g, " ").toUpperCase()
  }

  implicitWidth: 380
  implicitHeight: ncardBody.implicitHeight + 24
  radius: 12
  color: ncard.surface2
  border.width: 1
  border.color: ncard.live ? ncard.severityColor : ncard.border1
  Accessible.role: Accessible.StaticText
  Accessible.name: ncard.severityWord + " notification: " + String(ncard.entry.title || "") + ". " + String(ncard.entry.summary || "")

  ColumnLayout {
    id: ncardBody
    x: 14
    y: 12
    width: ncard.width - 28
    spacing: 8
    RowLayout {
      Layout.fillWidth: true
      spacing: 8
      Rectangle {
        Layout.alignment: Qt.AlignVCenter
        implicitWidth: 8
        implicitHeight: 8
        radius: 4
        color: ncard.severityColor
      }
      Text {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignVCenter
        textFormat: Text.PlainText
        text: String(ncard.entry.title || "")
        color: ncard.textHi
        font.pixelSize: 13
        font.bold: true
        elide: Text.ElideRight
      }
      Text {
        Layout.alignment: Qt.AlignVCenter
        visible: ncard.occurrences > 1
        textFormat: Text.PlainText
        text: "×" + ncard.occurrences
        color: ncard.textDim
        font.family: ncard.mono
        font.pixelSize: 11
        font.bold: true
      }
      Text {
        Layout.alignment: Qt.AlignVCenter
        visible: !ncard.live
        textFormat: Text.PlainText
        text: String(ncard.entry.lifecycle || "") === "dismissed" ? "DISMISSED" : "RESOLVED"
        color: ncard.textDim
        font.family: ncard.mono
        font.pixelSize: 9
        font.bold: true
        font.letterSpacing: 0.8
      }
      Item {
        Layout.alignment: Qt.AlignVCenter
        visible: ncard.hasDetails
        implicitWidth: 26
        implicitHeight: 26
        ExpandChevron {
          anchors.centerIn: parent
          open: ncard.expanded
          hovered: expandTap.containsMouse
          tile: 26
          glyph: 15
        }
        TapAction {
          id: expandTap
          objectName: "notificationExpand"
          anchors.fill: parent
          accessibleLabel: (ncard.expanded ? "Hide details for " : "Show details for ") + String(ncard.entry.title || "notification")
          focusRadius: 8
          onTriggered: ncard.expanded = !ncard.expanded
        }
      }
      ActionButton {
        objectName: "notificationDismiss"
        Layout.alignment: Qt.AlignVCenter
        visible: ncard.live && ncard.dismissible
        icon: "close"
        compact: true
        accessibleLabel: "Dismiss notification"
        onClicked: ncard.dismissRequested(ncard.identity)
      }
    }
    Text {
      Layout.fillWidth: true
      textFormat: Text.PlainText
      text: String(ncard.entry.summary || "")
      visible: String(ncard.entry.summary || "") !== ""
      color: ncard.textLo
      font.pixelSize: 12
      wrapMode: Text.WordWrap
      lineHeight: 1.2
    }
    RowLayout {
      Layout.fillWidth: true
      spacing: 8
      visible: ncard.live && ncard.actionList.length > 0
      Repeater {
        model: ncard.actionList
        delegate: ActionButton {
          required property var modelData
          objectName: "notificationAction_" + String(modelData)
          compact: true
          label: ncard.actionLabel(String(modelData))
          onClicked: ncard.actionRequested(ncard.identity, String(modelData))
        }
      }
      Item {
        Layout.fillWidth: true
      }
    }
    ColumnLayout {
      Layout.fillWidth: true
      spacing: 6
      visible: ncard.expanded
      Repeater {
        model: ncard.detailLines
        delegate: Text {
          required property var modelData
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: "• " + String(modelData)
          color: ncard.textDim
          font.pixelSize: 11
          wrapMode: Text.WordWrap
          lineHeight: 1.2
        }
      }
      RowLayout {
        Layout.fillWidth: true
        spacing: 8
        ActionButton {
          objectName: "notificationAdvanced"
          visible: ncard.diagnosticsText !== ""
          compact: true
          label: ncard.advanced ? "HIDE TRACE" : "ADVANCED"
          accessibleLabel: ncard.advanced ? "Hide advanced diagnostics" : "Show advanced diagnostics"
          onClicked: ncard.advanced = !ncard.advanced
        }
        ActionButton {
          objectName: "notificationCopyDiagnostics"
          visible: ncard.backendEntry
          compact: true
          label: "COPY DIAGNOSTICS"
          accessibleLabel: "Copy redacted diagnostics"
          onClicked: ncard.copyRequested(ncard.identity)
        }
        ActionButton {
          objectName: "notificationReportIssue"
          visible: ncard.backendEntry
          compact: true
          label: "REPORT ISSUE"
          accessibleLabel: "Open a reviewable issue draft"
          onClicked: ncard.reportRequested(ncard.identity)
        }
        Item {
          Layout.fillWidth: true
        }
      }
      Rectangle {
        Layout.fillWidth: true
        visible: ncard.advanced && ncard.diagnosticsText !== ""
        implicitHeight: Math.min(160, traceText.contentHeight + 16)
        color: ncard.surface0
        radius: 6
        border.width: 1
        border.color: ncard.border1
        Flickable {
          anchors.fill: parent
          anchors.margins: 8
          clip: true
          contentWidth: width
          contentHeight: traceText.contentHeight
          ScrollBar.vertical: ScrollBar {}
          TextEdit {
            id: traceText
            width: parent.width
            readOnly: true
            selectByMouse: true
            selectByKeyboard: true
            textFormat: TextEdit.PlainText
            wrapMode: TextEdit.Wrap
            text: ncard.diagnosticsText
            color: ncard.textDim
            font.family: ncard.mono
            font.pixelSize: 10
            selectionColor: ncard.accentDim
            selectedTextColor: ncard.textHi
          }
        }
      }
    }
  }
}

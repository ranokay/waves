import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "primitives" as Primitives

// Realtime console: tail of the dev log for debugging. The
// poll runs while open only (1s, capped lines), so a quiet app stays
// quiet; level filter + follow live in QML over the returned text, and
// copy/export ride the existing backend slots (copyLogs reuses the tail,
// exportDiagnostics the redacted bundle).
// 'host' is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load; the drawer reads the window
// bounds through it.
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Drawer {
  id: logsDrawer
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color green: "#3ef08a"   // LOSSLESS tier + done state
  readonly property color line1: "#22262d"   // row dividers
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"
  edge: Qt.RightEdge
  height: host.height
  width: Math.max(480, Math.min(host.width - 80, 640))
  background: Rectangle {
    color: surface
    border.color: line1
  }
  property string logsRaw: ""
  // Minimum level shown: 0 all, 1 info+, 2 warning+, 3 error only.
  // Lines without a level token (traceback continuations) follow the
  // previous line's level.
  property int logsMinLevel: 0
  property bool logsFollow: true
  property bool logsExportBusy: false
  property string logsExportPath: ""
  property bool logsExportFailed: false
  function logsRefresh() {
    logsRaw = waves.logTail(500)
  }
  function logsLevelOf(line) {
    var m = /^\d\d:\d\d:\d\d\.\d+\s+([A-Z]+)\s/.exec(line)
    var lv = m ? m[1] : ""
    if (lv === "DEBUG")
      return 0
    if (lv === "INFO")
      return 1
    if (lv === "WARN" || lv === "WARNING")
      return 2
    if (lv === "ERROR" || lv === "CRITICAL")
      return 3
    return -1
  }
  function logsFiltered() {
    if (logsMinLevel <= 0)
      return logsRaw
    var lines = logsRaw.split("\n")
    var out = []
    var carry = 1
    for (var i = 0; i < lines.length; i++) {
      var lv = logsLevelOf(lines[i])
      if (lv >= 0)
        carry = lv
      if (carry >= logsMinLevel)
        out.push(lines[i])
    }
    return out.join("\n")
  }
  function logsLineCount() {
    return logsRaw === "" ? 0 : logsRaw.split("\n").length
  }
  onOpenedChanged: if (opened) {
    logsExportFailed = false
    logsRefresh()
  }
  Timer {
    id: logsPoll
    interval: 1000
    repeat: true
    running: logsDrawer.opened
    onTriggered: logsDrawer.logsRefresh()
  }
  Connections {
    target: waves
    function onDiagnosticsExported(path) {
      if (!logsDrawer.opened)
        return
      logsDrawer.logsExportBusy = false
      logsDrawer.logsExportPath = path
      logsDrawer.logsExportFailed = (path === "")
    }
  }
  ColumnLayout {
    anchors.fill: parent
    anchors.margins: 16
    spacing: 12
    RowLayout {
      Layout.fillWidth: true
      Text {
        text: "Logs"
        color: textHi
        font.pixelSize: 16
        font.bold: true
      }
      Item {
        Layout.fillWidth: true
      }
      SpecBtn {
        id: logsCloseBtn
        icon: "close"
        accessibleLabel: "Close logs"
        onClicked: logsDrawer.close()
      }
    }
    // Level filter chips: minimum level shown.
    RowLayout {
      Layout.fillWidth: true
      spacing: 8
      Repeater {
        model: [[0, "ALL"], [1, "INFO"], [2, "WARNING"], [3, "ERROR"]]
        delegate: Rectangle {
          required property var modelData
          readonly property bool on: logsDrawer.logsMinLevel === modelData[0]
          radius: 8
          implicitHeight: 26
          implicitWidth: logChipTx.implicitWidth + 20
          color: on ? accentCont : "transparent"
          border.color: on ? accentDim : border1
          Text {
            id: logChipTx
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: modelData[1]
            color: on ? accent : textLo
            font.pixelSize: 11
            font.bold: true
          }
          TapAction {
            objectName: "logLevelChip"
            anchors.fill: parent
            accessibleLabel: "Log level " + modelData[1]
            role: Accessible.RadioButton
            checkable: true
            checked: on
            focusRadius: 8
            onTriggered: logsDrawer.logsMinLevel = modelData[0]
          }
        }
      }
      Item {
        Layout.fillWidth: true
      }
      Rectangle {
        radius: 8
        implicitHeight: 26
        implicitWidth: logFollowTx.implicitWidth + 20
        color: logsDrawer.logsFollow ? accentCont : "transparent"
        border.color: logsDrawer.logsFollow ? accentDim : border1
        Text {
          id: logFollowTx
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: "FOLLOW"
          color: logsDrawer.logsFollow ? accent : textLo
          font.pixelSize: 11
          font.bold: true
        }
        TapAction {
          objectName: "logFollowChip"
          anchors.fill: parent
          accessibleLabel: "Follow new log lines"
          role: Accessible.CheckBox
          checkable: true
          checked: logsDrawer.logsFollow
          focusRadius: 8
          onTriggered: {
            logsDrawer.logsFollow = !logsDrawer.logsFollow
            if (logsDrawer.logsFollow)
              logsFlick.contentY = Math.max(0, logsFlick.contentHeight - logsFlick.height)
          }
        }
      }
    }
    Flickable {
      id: logsFlick
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      contentWidth: logsText.width
      contentHeight: logsText.height
      ScrollBar.vertical: ScrollBar {}
      TextEdit {
        id: logsText
        width: logsFlick.width
        readOnly: true
        selectByMouse: true
        selectByKeyboard: true
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.Wrap
        color: textLo
        selectionColor: accentDim
        selectedTextColor: textHi
        font.family: mono
        font.pixelSize: 11
        text: logsDrawer.logsRaw === "" ? "No log lines yet — they appear here as the app works." : logsDrawer.logsFiltered()
      }
      // New lines stick to the bottom while following; a manual
      // scroll up takes over (FOLLOW unchecks) until re-enabled.
      onContentHeightChanged: if (logsDrawer.logsFollow)
        contentY = Math.max(0, contentHeight - height)
      onContentYChanged: {
        if (logsDrawer.logsFollow && contentY < contentHeight - height - 40)
          logsDrawer.logsFollow = false
      }
    }
    Text {
      textFormat: Text.PlainText
      text: "waves_dev.log · " + logsDrawer.logsLineCount() + " lines"
      color: textDim
      font.family: mono
      font.pixelSize: 10
    }
    RowLayout {
      Layout.fillWidth: true
      spacing: 8
      SpecBtn {
        label: logsDrawer.logsExportBusy ? "EXPORTING…" : "EXPORT"
        enabled: !logsDrawer.logsExportBusy
        onClicked: {
          logsDrawer.logsExportFailed = false
          logsDrawer.logsExportPath = ""
          logsDrawer.logsExportBusy = true
          waves.exportDiagnostics()
        }
      }
      SpecBtn {
        visible: logsDrawer.logsExportPath !== "" && !logsDrawer.logsExportBusy
        label: "SHOW FILE"
        onClicked: waves.revealDiagnostics(logsDrawer.logsExportPath)
      }
      SpecBtn {
        label: "COPY"
        onClicked: waves.copyLogs()
      }
      Item {
        Layout.fillWidth: true
      }
      Text {
        visible: logsDrawer.logsExportPath !== "" && !logsDrawer.logsExportBusy
        textFormat: Text.PlainText
        text: "✓ Saved"
        color: green
        font.pixelSize: 12
        Layout.alignment: Qt.AlignVCenter
      }
      Text {
        visible: logsDrawer.logsExportFailed
        textFormat: Text.PlainText
        text: "Export failed"
        color: red
        font.pixelSize: 12
        Layout.alignment: Qt.AlignVCenter
      }
    }
  }
}

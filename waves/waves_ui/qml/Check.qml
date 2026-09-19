import QtQuick

// Small square checkbox.
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Rectangle {
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentText: "#03210e"   // ink on a green fill
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)

  property bool checked: false
  signal toggled
  width: 18
  height: 18
  radius: 4
  color: checked ? accent : "transparent"
  border.color: checked ? accent : outline
  border.width: 2
  Ico {
    anchors.centerIn: parent
    visible: parent.checked
    name: "check"
    color: accentText
    size: 12
    bold: 8
  }
  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: parent.toggled()
  }
}

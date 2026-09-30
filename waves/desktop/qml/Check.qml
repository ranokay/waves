import QtQuick
import "primitives" as Primitives

// Small square checkbox.
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: chk
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentText: "#03210e"   // ink on a green fill
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)

  property bool checked: false
  // Callers supply the spoken name; unnamed optional checks stay out of
  // the keyboard chain until they have a meaningful action label.
  property string accessibleLabel: ""
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
  TapAction {
    anchors.fill: parent
    anchors.margins: -5
    accessibleLabel: chk.accessibleLabel
    role: Accessible.CheckBox
    checkable: true
    checked: chk.checked
    focusRadius: 4
    activeFocusOnTab: chk.visible && chk.enabled && chk.accessibleLabel !== ""
    onTriggered: chk.toggled()
  }
}

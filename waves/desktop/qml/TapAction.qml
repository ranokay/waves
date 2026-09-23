import QtQuick

// The shared keyboard-activatable tap area: the MouseArea half of the
// label-plus-tap-area pattern, carrying the metadata a pointer-only MouseArea
// lacks. The host draws the label and passes its spoken name; the pointer,
// the reader's press action and Return/Enter/Space all run the one
// `triggered` handler, so no path can drift from another.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
MouseArea {
  id: ta
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  // The spoken name. Every adopted control sets it: a button a reader cannot
  // name is worse than no button.
  property string accessibleLabel: ""
  // The focus ring's corner radius, so a ring on a rounded host matches the
  // host's own corner.
  property real focusRadius: 6
  signal triggered
  hoverEnabled: true
  cursorShape: ta.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
  onClicked: ta.triggered()
  // An inert control leaves the tab order, like every other button here.
  activeFocusOnTab: ta.visible && ta.enabled
  Accessible.role: Accessible.Button
  Accessible.name: ta.accessibleLabel
  Accessible.onPressAction: function () {
    if (ta.enabled)
      ta.triggered()
  }
  Keys.onReturnPressed: function (event) {
    if (!event.isAutoRepeat && ta.enabled) {
      event.accepted = true
      ta.triggered()
    }
  }
  Keys.onEnterPressed: function (event) {
    if (!event.isAutoRepeat && ta.enabled) {
      event.accepted = true
      ta.triggered()
    }
  }
  Keys.onSpacePressed: function (event) {
    if (!event.isAutoRepeat && ta.enabled) {
      event.accepted = true
      ta.triggered()
    }
  }
  // The focus ring a custom tap area draws for itself: an overlay, so the
  // host's own fill/border recipe is never repainted.
  Rectangle {
    anchors.fill: parent
    radius: ta.focusRadius
    color: "transparent"
    border.width: 2
    border.color: ta.accent
    visible: ta.activeFocus
  }
}

import QtQuick
import QtQuick.Layouts
import "primitives" as Primitives

// Tap-card action: the pop-ups' shared primary-action shape. A full-width
// tinted card with the label left and an arrow right, so actions read the
// same as the option cards (the card IS the button). danger tints it red.
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: ga
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color redCont: "#2a0e0c"
  readonly property color surface3: "#1d2128"   // art bg / unlit meter / inset
  readonly property color textHi: "#e6e8ec"
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)

  property string label: ""
  property bool danger: false
  property bool neutral: false      // grey secondary style (e.g. "keep" beside a green CTA)
  property bool showArrow: true     // hide when two GateActions sit side by side
  signal clicked
  readonly property color fg: neutral ? textHi : (danger ? red : accent)
  readonly property color bg: neutral ? surface3 : (danger ? redCont : accentCont)
  readonly property color bd: neutral ? outline : (danger ? Qt.alpha(red, 0.55) : accentDim)
  Layout.fillWidth: true
  implicitHeight: 46
  radius: 10
  color: gaMa.containsMouse && ga.enabled ? Qt.lighter(bg, 1.35) : bg
  border.width: 1
  border.color: bd
  RowLayout {
    anchors.fill: parent
    anchors.leftMargin: 14
    anchors.rightMargin: 14
    spacing: 10
    Text {
      textFormat: Text.PlainText
      text: ga.label
      color: ga.fg
      font.pixelSize: 13
      font.bold: true
      font.family: uiFont
      Layout.fillWidth: true
      elide: Text.ElideRight
      horizontalAlignment: ga.showArrow ? Text.AlignLeft : Text.AlignHCenter
    }
    Ico {
      visible: ga.showArrow
      name: "arrow-right"
      color: ga.fg
      size: 15
    }
  }
  TapAction {
    id: gaMa
    anchors.fill: parent
    // The host's own state, not the tap area's default: a disabled gate
    // action is no tab stop, no press target and no hand cursor.
    enabled: ga.enabled
    accessibleLabel: ga.label
    focusRadius: ga.radius
    onTriggered: ga.clicked()
  }
}

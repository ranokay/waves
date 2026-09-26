import QtQuick
import "primitives" as Primitives

// Hugging outlined button used wherever a surface needs one explicit action
// (dialog rows, section headers, the queue and logs drawers): one word or one
// Phosphor glyph in a rectangle, with primary / danger / warn / compact faces,
// keyboard activation and an overlay focus ring.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: sb
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property int btnPadH: 12   // label padding, left/right
  readonly property int btnPadV: 7   // label padding, top/bottom
  readonly property int btnRad: 8   // button corner radius
  readonly property real btnTrack: 0   // label letter-spacing
  readonly property color gold: "#ffb01f"   // HI-RES / VIDEO tier + meter mid band
  readonly property color goldCont: "#2a2008"
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color redCont: "#2a0e0c"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)
  property string label: ""
  property bool primary: false
  // GateAction's red recipe (red on redCont, translucent red border) on
  // the hugging shape, for the destructive half of a button pair.
  property bool danger: false
  // The same recipe in the palette's gold, for an action that interrupts
  // without discarding anything (pausing the queue). Not danger: nothing
  // is lost, and not primary: it is not the way forward either.
  property bool warn: false
  // Chip scale, for a button riding a section header or another dense
  // row: same fill/border/hover recipe, mono caps at the label size those
  // headers already use, so it reads as part of the header rather than a
  // dialog button that wandered in.
  property bool compact: false
  // A Phosphor glyph in place of the word, on a square of exactly the
  // button height, so it lines up with the worded buttons beside it. For
  // an action whose glyph says it faster than any label could (closing a
  // panel), where a word would only cost room in a crowded header.
  property string icon: ""
  // An explicit screen-reader name for a control whose visible word is
  // empty or does not say enough (an icon-only close, a count badge).
  property string accessibleLabel: ""
  readonly property bool iconOnly: icon !== "" && label === ""
  signal clicked
  // Accessible as a button and reachable with Tab; Enter/Space fire the
  // same clicked() the pointer does, so every dialog action (queue
  // PAUSE/STOP/RETRY ALL/CLEAR, gate cards) works keyboard-only. The
  // focus ring is the accent border, since a custom Rectangle draws none.
  activeFocusOnTab: visible
  Accessible.role: Accessible.Button
  Accessible.name: sb.accessibleLabel !== "" ? sb.accessibleLabel : (sb.label !== "" ? sb.label : (sb.icon !== "" ? sb.icon.charAt(0).toUpperCase() + sb.icon.slice(1) : "Button"))
  Accessible.onPressAction: function () {
    if (sb.enabled)
      sb.clicked()
  }
  Keys.onReturnPressed: function (event) {
    if (!event.isAutoRepeat && sb.enabled) {
      event.accepted = true
      sb.clicked()
    }
  }
  Keys.onEnterPressed: function (event) {
    if (!event.isAutoRepeat && sb.enabled) {
      event.accepted = true
      sb.clicked()
    }
  }
  Keys.onSpacePressed: function (event) {
    if (!event.isAutoRepeat && sb.enabled) {
      event.accepted = true
      sb.clicked()
    }
  }
  readonly property color bg: danger ? redCont : warn ? goldCont : (primary ? accentCont : "transparent")
  implicitWidth: iconOnly ? implicitHeight : sbTxt.implicitWidth + (compact ? 9 : btnPadH) * 2
  implicitHeight: sbTxt.implicitHeight + (compact ? 3 : btnPadV) * 2
  radius: compact ? 5 : btnRad
  color: (sbMa.containsMouse && (sb.primary || sb.danger || sb.warn)) ? Qt.lighter(sb.bg, 1.35) : sb.bg
  border.width: 1
  border.color: danger ? Qt.alpha(red, 0.55) : warn ? Qt.alpha(gold, 0.55) : (primary ? accentDim : border1)
  Behavior on color {
    ColorAnimation {
      duration: 110
    }
  }
  Text {
    id: sbTxt
    anchors.centerIn: parent
    // Kept loaded while icon-only (empty, invisible): its line height is
    // what makes the square square, so it has to keep measuring.
    visible: !sb.iconOnly
    textFormat: Text.PlainText
    text: sb.label
    color: sb.danger ? red : sb.warn ? gold : (sb.primary ? accent : (sbMa.containsMouse ? textHi : textLo))
    font.family: sb.compact ? mono : uiFont
    font.pixelSize: sb.compact ? 10 : 13
    font.bold: true
    font.letterSpacing: sb.compact ? 1.4 : btnTrack
  }
  Ico {
    visible: sb.icon !== ""
    anchors.centerIn: parent
    name: sb.icon
    size: sb.compact ? 11 : 14
    bold: 8
    color: sbTxt.color   // one recipe for the word and the glyph, hover included
  }
  MouseArea {
    id: sbMa
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: sb.clicked()
  }
  // The keyboard focus ring (a custom Rectangle draws none): an overlay
  // so it never repaints the danger/warn/primary border recipe.
  Rectangle {
    anchors.fill: parent
    radius: sb.radius
    color: "transparent"
    border.width: 2
    border.color: accent
    visible: sb.activeFocus
  }
}

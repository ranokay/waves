import QtQuick

// Queued glyph (chosen in the queued-descent lab): a 3-bar list, your
// item is the bottom bar. The accent highlight ping-pongs down and back
// up the stack (350ms per step, never pausing), phase-aligned via
// baseTick so it always starts at the top bar the moment the queued
// state appears. Steps off the host's shared marchTick, no per-frame
// animation (`marchTick` is required, so a missed binding fails at
// load).
// Split out of Main.qml (#315 slice 2). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml
// convention; keep them in step if the palette changes.

Column {
  id: qs
  required property int marchTick
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentDim: "#22a64a"   // terminal-button border

  property real barW: 12
  property int baseTick: 0
  Component.onCompleted: baseTick = marchTick
  onVisibleChanged: if (visible)
    baseTick = marchTick
  // Gated on visible so an idle button doesn't re-evaluate this on every
  // 50ms tick: hidden, the binding's only dependency is `visible` itself.
  readonly property int step: visible ? Math.floor(((marchTick - baseTick + 100000) % 100000) / 7) % 4 : 0
  readonly property int walk: step === 3 ? 1 : step   // 0,1,2,1 bounce
  spacing: 2.5
  Repeater {
    model: 3
    delegate: Rectangle {
      required property int index
      width: qs.barW
      height: 2.5
      radius: 0   // sharp LED bars
      anchors.horizontalCenter: parent.horizontalCenter
      color: index === qs.walk ? accent : accentDim
      opacity: index === qs.walk ? 1.0 : 0.45
    }
  }
}

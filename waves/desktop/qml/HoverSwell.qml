import QtQuick
import "primitives" as Primitives

// Hover swell: the control's outline turns
// bright accent and breathes while the pointer is on it. Light only, no
// travel: the line keeps its resting weight, exit is a fade in place.
// Scoped to the clickable region, so on the two-up pills each half lights
// by itself (outer corners rounded, square edge on the divider side).
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.

Rectangle {
  id: hs
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property real btnBorderW: 1.5
  readonly property int btnRad: 8              // button corner radius

  property bool on: false
  property real radL: btnRad     // 0 on the side that meets a divider
  property real radR: btnRad
  property real pulse: 0              // 0..1, the slow breath
  property color tone: accent    // the frame colour family (gold on the library claim)
  color: "transparent"
  border.width: btnBorderW
  border.color: Qt.lighter(hs.tone, 1.04 + 0.14 * pulse)
  topLeftRadius: radL
  bottomLeftRadius: radL
  topRightRadius: radR
  bottomRightRadius: radR
  // In fast and flat, out slow and eased, so crossing the PREVIEW |
  // DOWNLOAD divider hands the light over without a gap.
  // States, not a Behavior: a Behavior whose duration binding also reads
  // hs.on captures the OLD value when the flip triggers it, which swaps
  // the two durations (262ms in, 98ms out, exactly reversed).
  // A transition is picked by direction, so it cannot race the flag.
  opacity: 0
  states: State {
    name: "lit"
    when: hs.on
    PropertyChanges {
      target: hs
      opacity: 1
    }
  }
  transitions: [
    Transition {
      to: "lit"
      NumberAnimation {
        property: "opacity"
        duration: 90
        easing.type: Easing.Linear
      }
    },
    Transition {
      from: "lit"
      NumberAnimation {
        property: "opacity"
        duration: 260
        easing.type: Easing.OutQuad
      }
    }
  ]
  // Slow and symmetric, so it reads as the control being alive rather
  // than as an animation starting.
  SequentialAnimation {
    running: hs.on
    loops: Animation.Infinite
    alwaysRunToEnd: true
    NumberAnimation {
      target: hs
      property: "pulse"
      from: 0
      to: 1
      duration: 1100
      easing.type: Easing.InOutSine
    }
    NumberAnimation {
      target: hs
      property: "pulse"
      from: 1
      to: 0
      duration: 1100
      easing.type: Easing.InOutSine
    }
  }
}

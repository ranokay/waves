import QtQuick

// Entrance rise for Browse shelves: cards lift in, gated on the motion preference.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.hoverMotion
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Item {
  id: riser
  required property var host

  property bool on: false
  // Far enough to clear the bottom edge of any art tile (clip: true), so
  // the control is genuinely offscreen rather than peeking. With motion
  // off it rests at 0 and only the opacity animates.
  property real travel: 44
  readonly property bool motion: host.hoverMotion
  property real yShift: motion ? travel : 0
  opacity: 0
  visible: opacity > 0
  transform: Translate {
    y: riser.yShift
  }
  states: State {
    name: "on"
    when: riser.on
    PropertyChanges {
      target: riser
      yShift: 0
      opacity: 1
    }
  }
  transitions: [
    Transition {
      to: "on"
      NumberAnimation {
        property: "yShift"
        duration: riser.motion ? 240 : 0
        easing.type: Easing.OutBack
        easing.overshoot: 1.2
      }
      NumberAnimation {
        property: "opacity"
        duration: riser.motion ? 180 : 160
        easing.type: Easing.OutQuad
      }
    },
    Transition {
      from: "on"
      NumberAnimation {
        property: "yShift"
        duration: riser.motion ? 150 : 0
        easing.type: Easing.InQuad
      }
      NumberAnimation {
        property: "opacity"
        duration: riser.motion ? 150 : 160
        easing.type: Easing.InQuad
      }
    }
  ]
}

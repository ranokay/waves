import QtQuick

// Odometer digit for the folder badge: the next value drops in from above
// while the old one falls away, clipped to the badge (220ms, OutQuad).
// The final tick rolls in a checkmark instead of 0.
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Item {
  id: od
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)

  property string value: "0"
  property string shown: "0"
  property string _pending: "0"
  implicitWidth: Math.max(odA.implicitWidth, odB.implicitWidth)
  implicitHeight: odA.implicitHeight
  clip: true
  Component.onCompleted: shown = value
  onValueChanged: {
    // Land any roll in flight BEFORE the no-op check. Returning early
    // on value === shown would leave the animation running, and its
    // ScriptAction would then latch the abandoned _pending, sticking
    // the digit on a number the badge no longer holds. LibList pools
    // delegates (reuseItems), so a fast flick rebinds one A -> B -> A
    // well inside the 220ms roll and a folder ends up wearing another
    // one's count.
    if (odAnim.running) {
      odAnim.stop()
      od.shown = od._pending
      odA.y = 0
      odB.y = -od.height
    }
    if (value === od.shown)
      return
    od._pending = value
    odB.text = value
    odAnim.restart()
  }
  Text {
    id: odA
    textFormat: Text.PlainText
    text: od.shown
    color: accent
    font.family: mono
    font.pixelSize: 12
    font.bold: true
  }
  Text {
    id: odB
    textFormat: Text.PlainText
    text: ""
    color: accent
    font.family: mono
    font.pixelSize: 12
    font.bold: true
    y: -od.height
  }
  SequentialAnimation {
    id: odAnim
    ParallelAnimation {
      NumberAnimation {
        target: odA
        property: "y"
        from: 0
        to: od.height
        duration: 220
        easing.type: Easing.OutQuad
      }
      NumberAnimation {
        target: odB
        property: "y"
        from: -od.height
        to: 0
        duration: 220
        easing.type: Easing.OutQuad
      }
    }
    ScriptAction {
      script: {
        od.shown = od._pending
        odA.y = 0
        odB.y = -od.height
      }
    }
  }
}

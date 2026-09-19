import QtQuick

// Recent-release mark: a mint dot and the word, no chip. Every other badge
// is a bordered pill about what you HAVE (library, quality); this one is
// about the calendar, so it stays out of their shape. The dot, breathing
// gently, keeps the word from reading as part of the date it usually
// follows. It decides
// nothing: callers bind visible to root.isNewRelease(). compact is the
// card caption size. settled is the caller saying you already have it
// (downloaded, or a full copy in the library): the mark stays, the breath
// stops, because the release is still new but no longer asking for you.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.bootContentShown / host.newPulseMs / host.onScreen
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Item {
  id: nt
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accentContTx: "#86ffaa"   // text on accent container
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)

  objectName: "newTag"
  property bool compact: false
  property bool settled: false
  readonly property bool pulsing: ntPulse.running
  // Where the word's capitals sit, measured from the glyphs, so a caller
  // beside much larger type can line the two up by eye rather than by
  // their boxes (a 26px title's box centre is not its capitals' centre).
  readonly property real capMiddle: ntWord.y + ntWord.baselineOffset - ntFm.tightBoundingRect("NEW").height / 2
  FontMetrics {
    id: ntFm
    font: ntWord.font
  }
  implicitHeight: compact ? 14 : 18
  implicitWidth: ntDot.width + ntWord.anchors.leftMargin + ntWord.implicitWidth
  Rectangle {
    id: ntDot
    width: parent.compact ? 4 : 5
    height: width
    radius: width / 2
    color: accentContTx
    anchors.verticalCenter: parent.verticalCenter
    // A very gentle breath, on the render thread: an OpacityAnimator
    // costs the GUI thread nothing per frame, where a NumberAnimation
    // on every marked row and card would evaluate on it at display
    // rate. It runs only while it can be seen, never under the launch
    // reveal, and starts on the next shared beat of the wall clock, so
    // a shelf of dots breathes in step instead of twinkling out of phase.
    readonly property bool breathing: visible && host.onScreen && host.bootContentShown >= 1 && !nt.settled
    function breathe() {
      ntPulse.stop()
      ntBeat.stop()
      opacity = 1
      if (!breathing)
        return
      ntBeat.interval = Math.max(1, host.newPulseMs - Date.now() % host.newPulseMs)
      ntBeat.start()
    }
    onBreathingChanged: breathe()
    Component.onCompleted: breathe()
    Timer {
      id: ntBeat
      repeat: false
      onTriggered: ntPulse.start()
    }
    SequentialAnimation {
      id: ntPulse
      loops: Animation.Infinite
      OpacityAnimator {
        target: ntDot
        from: 1
        to: 0.5
        duration: host.newPulseMs / 2
        easing.type: Easing.InOutSine
      }
      OpacityAnimator {
        target: ntDot
        from: 0.5
        to: 1
        duration: host.newPulseMs / 2
        easing.type: Easing.InOutSine
      }
    }
  }
  Text {
    id: ntWord
    anchors.left: ntDot.right
    anchors.leftMargin: parent.compact ? 4 : 5
    anchors.verticalCenter: parent.verticalCenter
    textFormat: Text.PlainText
    text: "NEW"
    color: accentContTx
    font.family: mono
    font.pixelSize: parent.compact ? 10 : 11
    font.bold: true
    font.letterSpacing: 0.8
  }
}

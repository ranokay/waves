import QtQuick

// A word that "decrypts" in: every glyph starts scrambled and locks left
// to right. Carried over from the queue design lab for the ledger's
// status cell; any target change while live replays the decode, so a
// state flip (QUEUED -> DOWNLOADING -> COMPLETED) announces itself.
// Split out of Main.qml (#315 slice 4). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Text {
  id: dt
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  property string target: ""
  property int _step: 0
  property bool _live: false
  readonly property string glyphs: "#%&*+=<>/\\~"
  textFormat: Text.PlainText
  font.family: mono
  Component.onCompleted: {
    text = target
    _live = true
  }
  onTargetChanged: if (_live)
    replay()
  else
    text = target
  function replay() {
    _step = 0
    dtTimer.restart()
    _frame()
  }
  function _frame() {
    var out = ""
    for (var i = 0; i < target.length; ++i)
      out += i < _step ? target.charAt(i) : glyphs.charAt(Math.floor(Math.random() * glyphs.length))
    text = out
  }
  Timer {
    id: dtTimer
    interval: 28
    repeat: true
    onTriggered: {
      dt._step++
      if (dt._step > dt.target.length) {
        dt.text = dt.target
        stop()
      } else
        dt._frame()
    }
  }
}

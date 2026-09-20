import QtQuick

// Drives the "matrix decrypt" paste-in for a TextField: scrambled glyphs settle
// left-to-right into the pasted text, then decoded(text) fires. We never read the
// clipboard, only react to what the field received. Shared by search + login.
QtObject {
  id: dc
  required property var field          // the TextField it animates
  property var glyph: null             // optional PasteGlyph to fill in sync
  property bool decoding: false
  signal begun
  signal decoded(string text)
  property string _final: ""
  property int _locked: 0
  property int _step: 1                 // chars revealed per tick, keeps the
  property int _prevLen: 0              // total decode ~fixed even for long URLs
  readonly property int _maxTicks: 24   // ~24 * 26ms ~= 0.6s, any length
  readonly property string _glyphs: "ABCDEF0123456789/:.~#@$%&abcdefxyz"
  function _scr(n) {
    var s = ""
    for (var i = 0; i < n; i++)
      s += _glyphs.charAt(Math.floor(Math.random() * _glyphs.length))
    return s
  }
  // Call from the field's onTextChanged: a multi-char jump that typing can't
  // produce is treated as a paste and animated in.
  // Stop a decode in flight and forget its term: a caller clearing the
  // field must not have the animation rewrite it a tick later.
  function cancel() {
    _timer.stop()
    decoding = false
    _final = ""
    _locked = 0
    _prevLen = 0
  }
  function noteTextChanged() {
    if (!decoding && field.text.length - _prevLen >= 4)
      run(field.text)
    _prevLen = field.text.length
  }
  function run(t) {
    if (!t)
      return
    t = ("" + t).replace(/\s+/g, " ").trim()
    if (!t.length)
      return
    _final = t
    _locked = 0
    decoding = true
    begun()
    _step = Math.max(1, Math.ceil(_final.length / _maxTicks))
    // cap the run length
    field.text = _scr(t.length)
    // start scrambled, no flash of the raw text
    field.forceActiveFocus()
    _timer.restart()
    if (glyph)
      glyph.play()
  }
  property Timer _timer: Timer {
    interval: 26
    repeat: true
    onTriggered: {
      dc._locked += dc._step
      if (dc._locked >= dc._final.length) {
        dc.field.text = dc._final
        dc.decoding = false
        stop()
        dc.decoded(dc._final)
      } else {
        dc.field.text = dc._final.substring(0, dc._locked) + dc._scr(dc._final.length - dc._locked)
      }
    }
  }
}

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
  // The last text the decoder itself wrote. A change that is not this, seen
  // while a decode is actually running, is an outside write (a keyboard
  // paste lands straight in the field and bypasses the glyph's
  // cancel-first path), never the timer's own tick.
  property string _shown: ""
  // True while a restart's begun() is on the stack, so arming callers can
  // tell a replaced decode from a fresh one.
  property bool _restarting: false
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
    _shown = ""
    _locked = 0
    _prevLen = 0
  }
  function noteTextChanged() {
    // An outside write landing while a decode is actually running (the
    // timer is on, not a pinned hold) retires the running term: a keyboard
    // paste neither clears first nor cancels, so without this the in-flight
    // timer keeps the old term, rewrites the field back to it and submits
    // it. A paste-like jump restarts on the new text; anything smaller only
    // stops the decode, so neither a stale term submits nor transient
    // scramble bakes into a new one — the explicit submit paths (the
    // sign-in COMPLETE action, search Enter) stay available for the edit.
    // Paste-like mirrors the idle rule: a growth typing cannot produce, or
    // a full replacement (a same-length link swap is still a paste; an
    // overwrite keystroke misfiring here is accepted as the rarer error).
    // The timer's own ticks write _shown and never take this branch, and
    // run()'s opening write lands before the timer starts.
    if (decoding && _timer.running && field.text !== _shown) {
      var t = field.text
      var prevLen = _shown.length
      cancel()
      var growth = t.length - prevLen
      if (growth >= 4 || (t.length === prevLen && t.length >= 4)) {
        _restarting = true
        run(t)
        _restarting = false
      } else {
        _prevLen = t.length
      }
      return
    }
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
    // Record the write before making it: the assignment notifies
    // noteTextChanged synchronously, which must read it as our own.
    _shown = _scr(t.length)
    field.text = _shown
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
        dc._shown = dc._final
        dc.field.text = dc._shown
        dc.decoding = false
        stop()
        dc.decoded(dc._final)
      } else {
        dc._shown = dc._final.substring(0, dc._locked) + dc._scr(dc._final.length - dc._locked)
        dc.field.text = dc._shown
      }
    }
  }
}

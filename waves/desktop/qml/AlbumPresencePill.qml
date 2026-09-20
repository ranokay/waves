import QtQuick

// The album presence pill, self-resolving against the local scan index,
// placed right beside the album title. Static IN LIBRARY (or N OF M) with
// a quality-coded dot; the colour class is the whole quality story.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
LibraryTag {
  id: appl

  // The album's identity as ONE object ({artist, title, year, tracks}),
  // not four properties. Each property carried its own change handler, so
  // filling them in cost one QML->Python presence call each plus a fifth
  // from onCompleted: measured at 15 calls per album row and 750 for a
  // 50-row page, 22us apiece, ~16ms of GUI thread per page build. One
  // property is one binding evaluation and one call. Null (or no title)
  // means no album to ask about, and the pill stays hidden.
  property var album: null
  property var presence: null
  readonly property string albumTitle: (album && album.title) ? ("" + album.title) : ""
  // A recycled row is a new album, not news about this one.
  settleKey: appl.albumTitle
  property bool _resolved: false
  function _resolvePresence() {
    _resolved = true
    var a = appl.album
    presence = (a && a.title) ? waves.libraryAlbumPresence("" + (a.artist || ""), "" + a.title, "" + (a.year || ""), a.tracks || 0, a.duration_sec || 0) : null
  }
  onAlbumChanged: _resolvePresence()
  // Only if the binding above has not already answered: an unconditional
  // resolve here is the fifth call this component exists to avoid.
  Component.onCompleted: if (!_resolved)
    _resolvePresence()
  Connections {
    target: waves
    function onLibraryPresenceChanged() {
      appl._resolvePresence()
    }
  }
  visible: !!(presence && presence.present)
  have: presence ? (presence.local_tracks || 0) : 0
  total: (album && album.tracks) ? album.tracks : 0
  declared: presence ? (presence.local_declared || 0) : 0
  albumId: presence ? (presence.local_album_id || "") : ""
  qclass: presence ? (presence.local_class || "") : ""
  // The identity axis alone ("sure"): the "?" asks "is this really the
  // same album", so a proven match drops it even when the copy is short
  // on tracks (coverage is already spelled out as N OF M). Track pills
  // and the artist rollup have no identity proofs and keep theirs.
  proven: !!(presence && presence.present && presence.sure === true)
  // The Atmos micro-badge (§8.4): the album on disk holds Dolby Atmos Versions
  // beside its canonical set. Spoken as the pill's last word, so the
  // badge needs no second anchor beside a pill whose row already
  // reserves its width; libraries without Atmos never take this branch
  // and read exactly as before.
  readonly property bool atmos: !!(presence && presence.present && presence.has_atmos === true)
  extra: appl.atmos ? " · ATMOS TOO" : ""
}

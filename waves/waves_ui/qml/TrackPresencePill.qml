import QtQuick

// The track twin of AlbumPresencePill: the same LibraryTag, resolved
// against the per-track index, so a track row can say the exact song is on
// disk (an incomplete album's tracks included). One identity object for
// the same one-call-per-row economy as the album pill. Never shown for
// videos: the library scan only ever holds audio.
// `host` is Main.qml's root object, bound at every instantiation and
// required by the LibraryTag base, which declares it.
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
LibraryTag {
  id: tppl

  // {artist, title, album, year}; null (or no title) means nothing to ask
  // about. album/year name the release this track belongs to: they are
  // what the match can be PROVEN against, since a track carries no year
  // of its own and its title matches every edition that shares it. A row
  // that cannot name its album still gets a pill, it just keeps the "?".
  property var track: null
  property var presence: null
  // A recycled row is a new track, not news about this one.
  settleKey: (tppl.track && tppl.track.title) ? ("" + tppl.track.title) : ""
  property bool _resolved: false
  function _resolvePresence() {
    _resolved = true
    var t = tppl.track
    presence = (t && t.title) ? waves.libraryTrackPresence("" + (t.artist || ""), "" + t.title, "" + (t.album || ""), "" + (t.year || ""), t.duration_sec || 0) : null
  }
  onTrackChanged: _resolvePresence()
  Component.onCompleted: if (!_resolved)
    _resolvePresence()
  Connections {
    target: waves
    function onLibraryPresenceChanged() {
      tppl._resolvePresence()
    }
  }
  visible: !!(presence && presence.present)
  albumId: presence ? (presence.local_album_id || "") : ""
  qclass: presence ? (presence.local_class || "") : ""
  // The same identity axis the album pill reads, inherited from the
  // folder the copy was found in: a track sitting in an album this
  // library can prove is the release drops the "?" with it.
  proven: !!(presence && presence.present && presence.sure === true)
}

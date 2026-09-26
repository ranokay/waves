import QtQuick

// The library verdict a browse card carries, resolved ONCE per card. The
// hover strip needs it to colour its download half and the pill needs it
// to say what is held, and asking twice would be two QML->Python calls per
// card on a shelf of them (the economy AlbumPresencePill's single-object
// property exists for). Albums only: a playlist or a mix has no album
// identity to ask about, and must never wear one's badge.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load. It reads host.libStamp; the
// verdict itself comes from the payload's baked answer or the bridge.
QtObject {
  id: verdict
  required property var host
  property var card: ({})
  property var presence: null
  property bool _resolved: false
  // The answer the payload carries (card.lib, resolved on the worker that
  // built the page) serves the card's creation; only a later change (a
  // library publish) asks the bridge. A card being created is inside an
  // incubation slice, and a bridge call there waits its turn for the
  // interpreter behind every busy worker: sampled live at launch, that
  // wait was most of what the boot water dropped frames on. Keys are
  // checked with `in`: a payload built before the dressing existed simply
  // has no key and asks as before.
  function resolve(live) {
    _resolved = true
    var c = verdict.card
    if (!(c && c.kind === "album" && c.title)) {
      presence = null
      return
    }
    presence = (!live && ("lib" in c) && c.libStamp === host.libStamp) ? c.lib : waves.libraryAlbumPresence("" + (c.artist || ""), "" + c.title, "" + (c.year || ""), c.tracks || 0, c.duration_sec || 0, c.explicit === true ? 1 : -1)
  }
  onCardChanged: resolve(false)
  // Only if the binding above has not already answered: an unconditional
  // resolve here is a second QML->Python call per card on a shelf.
  Component.onCompleted: if (!_resolved)
    resolve(false)
  property Connections _conn: Connections {
    target: waves
    // A shelf builds a card for every kind, so the ones that will never
    // ask must not run a handler per card per committed batch of a
    // running scan.
    enabled: verdict.card.kind === "album"
    function onLibraryPresenceChanged() {
      verdict.resolve(true)
    }
  }
  readonly property bool present: !!(verdict.presence && verdict.presence.present === true)
  readonly property bool full: !!(verdict.presence && verdict.presence.full === true)
  readonly property bool sure: !!(verdict.presence && verdict.presence.sure === true)
  // The Atmos micro-badge (§8.4): the album on disk holds Dolby Atmos Versions
  // beside its canonical set.
  readonly property bool atmos: !!(verdict.presence && verdict.presence.has_atmos === true)
  // The three states the strip's download half can wear, exactly the ones
  // DownloadButton names: a proven complete copy, an unproven one, and a
  // partial copy (which stays a plain live download, since completing an
  // album is not a duplicate).
  readonly property string state: !verdict.present ? "" : !verdict.full ? "partial" : verdict.sure ? "proven" : "maybe"
  // A FULL claim gates its click the way the full button does: explain the
  // match, name the folder, leave Download anyway one click away. A tag
  // match must never be the end of the conversation.
  readonly property bool claim: verdict.state === "proven" || verdict.state === "maybe"
  // The shortest forms that still say which of the three is true, for the
  // ~90px control lines that cannot carry the full button's wording. A
  // partial copy spends them on the count itself, which is the thing worth
  // knowing.
  readonly property string word: {
    if (verdict.state === "proven")
      return "IN LIBRARY"
    if (verdict.state === "maybe")
      return "MAYBE"
    if (verdict.state === "partial") {
      var p = verdict.presence
      var held = p.local_tracks || 0
      var declared = p.local_declared || 0
      var want = declared > held ? declared : ((verdict.card && verdict.card.tracks) || 0)
      if (want > held)
        return held + " OF " + want
    }
    return "DOWNLOAD"
  }
}

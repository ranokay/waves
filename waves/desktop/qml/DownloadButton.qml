import QtQuick
import QtQuick.Controls.Basic

// Outlined terminal download button. Idle: ↓ + uppercase label. Running:
// a monospace ASCII bar (█ filled + ░ dim) + %. Done/failed: colour +
// glyph.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load. The button reads through it:
//   host.dlSt(id) / host.dlPct(id)  the live download holder for this id
//   host.libraryOn / host.dlInLibrary  the done-face wording
//   host.hoverMotion  the motion preference
//   host.ledPulse / host.shimmerPhase / host.queueEdgeHeld  the shared
//     clocks DotMatrix rides
//   host.qualFg / host.qualBorder / host.qualDot / host.qualTint  the tier
//     colour vocabulary
//   host.cancelQueuedMedia / host.openLibraryClaim /
//     host.openRedownloadGate / host.ownKeys / host.ownBatchHits  the
//     host's actions and batch helpers

Rectangle {
  id: db
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentContTx: "#86ffaa"   // text on accent container
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color accentText: "#03210e"   // ink on a green fill
  readonly property real btnBorderW: 1.5
  readonly property int btnPadH: 12             // label padding, left/right
  readonly property int btnPadV: 7              // label padding, top/bottom
  readonly property int btnRad: 8              // button corner radius
  readonly property real btnTrack: 0              // label letter-spacing
  readonly property color cyan: "#56c8d8"   // HIGH tier + queued
  readonly property color cyanCont: "#07232b"   // healthy-lossy pill container
  readonly property color cyanDim: "#3a8d99"
  readonly property color gold: "#ffb01f"   // HI-RES / VIDEO tier + meter mid band
  readonly property color goldCont: "#2a2008"
  readonly property color goldDim: "#b07d18"
  readonly property color greenCont: "#08230f"
  readonly property color greenDim: "#2aa862"
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color redCont: "#2a0e0c"
  readonly property color surface3: "#1d2128"   // art bg / unlit meter / inset
  readonly property color surfaceHi: "#22262e"   // toast
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)

  property string mediaId: ""
  property string label: "Download"
  // The media word the resolved label leads with ("TRACK IN LIBRARY",
  // "ALBUM DOWNLOADED"), so a done button says what it is talking about
  // instead of a bare IN LIBRARY. Derived from the idle label's own
  // noun; set `noun` where the label is generic ("Download" on a video
  // cell). Empty means the plain label, for buttons like "Download all"
  // whose scope has no one-word name.
  property string noun: ""
  readonly property string doneNoun: {
    if (noun !== "")
      return noun.toUpperCase()
    var l = label.toLowerCase()
    if (l.indexOf("videos") !== -1)
      return "VIDEOS"
    if (l.indexOf("video") !== -1)
      return "VIDEO"
    if (l.indexOf("track") !== -1)
      return "TRACK"
    if (l.indexOf("album") !== -1)
      return "ALBUM"
    if (l.indexOf("playlist") !== -1)
      return "PLAYLIST"
    if (l.indexOf("mix") !== -1)
      return "MIX"
    if (l.indexOf("artist") !== -1 || l.indexOf("discography") !== -1)
      return "DISCOGRAPHY"
    return ""
  }
  property var onTap: (function () {})
  // Chooser split button (spec 7.2)
  // chooserKind names what this control downloads (track, album,
  // playlist, mix, video, artist, folder, category). Track rows and
  // collection pages carry per-click support. Bulk sweeps keep Settings.
  property string chooserKind: "track"
  // The split-button Chooser is a control, not an Apple feature: the
  // bridge answers whether THIS row's provider metadata and kind carry
  // it, so a TIDAL-only install gets one and a provider that offers no
  // per-click options draws no chevron. QML names no provider.
  function computeChooserSupported() {
    if (db.chooserKind === "" || ("" + db.mediaId) === "")
      return false
    try {
      return waves.chooserSupported(db.mediaId, db.chooserKind) === true
    } catch (e) {
      return false
    }
  }
  readonly property bool showChooser: db.computeChooserSupported()
  property bool chooserBuilt: false
  readonly property bool chooserOpen: chooserLoader.item !== null && chooserLoader.item.visible
  property string chooserProvider: ""
  property string chooserTier: ""
  property string chooserAudio: "stereo"
  property bool chooserAtmosOnly: false
  property var chooserTiers: []
  property var chooserProviders: []
  property var chooserAudioOptions: ["stereo"]
  property bool chooserShowLyrics: false
  property bool chooserShowTtml: false
  property bool chooserShowArt: false
  property bool chooserLyricsEmbed: false
  property bool chooserLyricsFile: false
  property bool chooserLyricsTtml: false
  property bool chooserCoverEmbed: true
  property bool chooserCoverFile: true
  function refreshChooser() {
    var d = ({})
    try {
      d = waves.chooserDefaults(db.mediaId, db.chooserKind) || ({})
    } catch (e) {
      d = ({})
    }
    db.chooserProvider = "" + (d.provider || "")
    db.chooserTier = "" + (d.tier || "")
    db.chooserAudio = "" + (d.audioType || "stereo")
    db.chooserAtmosOnly = d.atmosOnly === true
    if (db.chooserAtmosOnly)
      db.chooserAudio = "atmos"
    db.chooserTiers = d.tiers || []
    db.chooserProviders = d.providers || []
    var audios = d.audioOptions || []
    db.chooserAudioOptions = audios.length > 0 ? audios : ["stereo"]
    db.chooserShowLyrics = d.showLyrics === true
    db.chooserShowTtml = d.showLyricsTtml === true
    db.chooserShowArt = d.showArt === true
    db.chooserLyricsEmbed = d.lyricsEmbed === true
    db.chooserLyricsFile = d.lyricsFile === true
    db.chooserLyricsTtml = d.lyricsTtml === true && db.chooserShowTtml
    db.chooserCoverEmbed = d.coverEmbed !== false
    db.chooserCoverFile = d.coverFile !== false
  }
  // What a click does, without the pointer: the same decision the tap
  // area and the keyboard/accessibility press action take (the gates
  // included), so a keyboard user cannot bypass a claim or a done face.
  function activate() {
    // A library claim is a guess, so it answers instead of ignoring.
    if (db.libClaim) {
      db.openLibraryClaim()
      return
    }
    // A recorded copy answers too: where it is, and REDOWNLOAD.
    if (db.st === "done" && db.canRedownload) {
      db.openRedownload()
      return
    }
    if (db.st === "running" || db.st === "done" || db.waiting)
      return
    db.onTap()
  }
  function accessibleName() {
    // The visible face names itself: the label carries the scope
    // ("Download album") and the library faces their own words, so the
    // reader hears what the button draws.
    var base = db.label !== "" ? db.label : "Download"
    if (db.libClaim)
      return (db.libGuess ? "Maybe in library: " : "In library: ") + base
    if (db.libPartialClaim)
      return "Partially in library: " + base
    if (db.st === "done")
      return db.canRedownload ? base + ", downloaded, menu for redownload" : base + ", downloaded"
    if (db.st === "failed")
      return base + ", failed"
    if (db.waiting)
      return base + ", queued, press Delete to cancel"
    if (db.st === "running")
      return base + ", downloading"
    return base + (db.showChooser ? ", press Down for download options" : "")
  }
  function chooserReachable() {
    return db.showChooser && !db.libClaim && !(db.st === "running" || db.waiting || db.st === "done")
  }
  // Inert faces leave the tab order, but the actionable ones stay: the
  // claim faces (MAYBE/IN LIBRARY) open their gate, and the done face
  // with REDOWNLOAD stays because it is actionable.
  activeFocusOnTab: db.visible && (db.libClaim || !(db.st === "running" || db.waiting || (db.st === "done" && !db.canRedownload)))
  Accessible.role: Accessible.Button
  Accessible.name: db.accessibleName()
  Accessible.onPressAction: db.activate()
  Keys.onReturnPressed: function (event) {
    if (!event.isAutoRepeat) {
      event.accepted = true
      db.activate()
    }
  }
  Keys.onEnterPressed: function (event) {
    if (!event.isAutoRepeat) {
      event.accepted = true
      db.activate()
    }
  }
  Keys.onSpacePressed: function (event) {
    if (!event.isAutoRepeat) {
      event.accepted = true
      db.activate()
    }
  }
  // The chooser is the second face; Down opens it for a keyboard user
  // exactly where the right-click/chevron path does. The key is only
  // swallowed when the chooser would really open, so list navigation is
  // never eaten by an inert face.
  Keys.onDownPressed: function (event) {
    if (db.chooserReachable()) {
      event.accepted = true
      db.openChooser()
    }
  }
  // A queued row's inline cancel has no pointer-only equivalent.
  Keys.onDeletePressed: function (event) {
    if (db.st === "queued" || db.waiting) {
      event.accepted = true
      host.cancelQueuedMedia(db.mediaId)
    }
  }
  function openChooser() {
    if (!db.showChooser)
      return
    if (db.st === "running" || db.waiting)
      return
    // An owned copy stays inert and a tag match keeps its gate, the
    // same rule the main face follows.
    if (db.libClaim) {
      db.openLibraryClaim()
      return
    }
    if (db.st === "done")
      return
    db.chooserBuilt = true
    db.refreshChooser()
    var m = chooserLoader.item
    if (m)
      m.open()
  }
  function closeChooser() {
    if (chooserLoader.item)
      chooserLoader.item.close()
  }
  function confirmChooser() {
    if (db.libClaim) {
      db.closeChooser()
      db.openLibraryClaim()
      return
    }
    if (db.st === "done" || db.st === "running" || db.waiting) {
      db.closeChooser()
      return
    }
    // The control's own verdict (the bridge's kind + capability rule),
    // not a second list spelled here: a kind or provider the bridge
    // turns off falls back to the plain click, exactly as the absent
    // chevron does.
    if (!db.showChooser) {
      try {
        db.onTap()
      } catch (e) {
        try {
          waves.uiLog("chooser", "chooser fallback failed: " + e, -1)
        } catch (e2) {}
      }
      db.closeChooser()
      return
    }
    var k = "" + (db.chooserKind || "")
    var tier = db.chooserAtmosOnly ? "" : ("" + (db.chooserTier || ""))
    var audio = db.chooserAtmosOnly ? "atmos" : ("" + (db.chooserAudio || ""))
    var toggles = {
      lyrics_embed: db.chooserLyricsEmbed,
      lyrics_file: db.chooserLyricsFile,
      lyrics_ttml_file: db.chooserLyricsTtml,
      metadata_cover_embed: db.chooserCoverEmbed,
      cover_album_file: db.chooserCoverFile
    }
    try {
      waves.downloadWithChooser(db.mediaId, k, tier, audio, toggles)
    } catch (e) {
      try {
        waves.uiLog("chooser", "downloadWithChooser failed: " + e, -1)
      } catch (e2) {}
      try {
        db.onTap()
      } catch (e3) {}
    }
    db.closeChooser()
  }
  // The Chooser's rows are real controls: the pointer, the
  // keyboard and a screen reader all take these one paths.
  function chooserPickTier(word) {
    db.chooserTier = "" + word
  }
  function chooserPickAudio(word) {
    db.chooserAudio = "" + word
  }
  function chooserToggle(key) {
    if (key === "lyrics_embed")
      db.chooserLyricsEmbed = !db.chooserLyricsEmbed
    else if (key === "lyrics_file")
      db.chooserLyricsFile = !db.chooserLyricsFile
    else if (key === "lyrics_ttml_file") {
      if (db.chooserShowTtml)
        db.chooserLyricsTtml = !db.chooserLyricsTtml
    } else if (key === "cover_embed")
      db.chooserCoverEmbed = !db.chooserCoverEmbed
    else if (key === "cover_file")
      db.chooserCoverFile = !db.chooserCoverFile
  }
  function saveChooserAsDefaults() {
    var vals = {
      provider: "" + (db.chooserProvider || ""),
      tier: "" + (db.chooserTier || ""),
      audioType: db.chooserAtmosOnly ? "atmos" : ("" + (db.chooserAudio || "")),
      lyrics_embed: db.chooserLyricsEmbed,
      lyrics_file: db.chooserLyricsFile,
      lyrics_ttml_file: db.chooserLyricsTtml,
      metadata_cover_embed: db.chooserCoverEmbed,
      cover_album_file: db.chooserCoverFile
    }
    try {
      waves.saveChooserDefaults(vals)
    } catch (e) {}
  }
  // Where the recorded copy behind `owned` lives (refreshOwned fills
  // both): ownInLibrary words the done face by THAT copy's location,
  // not by where downloads go today, and ownFolder is what the
  // redownload gate names.
  property bool ownInLibrary: false
  property string ownFolder: ""
  // What an owned done click redownloads. Derived from the done noun;
  // set gateKind where the noun does not name a downloadable kind.
  // Empty means the owned face stays inert (a "Download all" has no
  // single thing to fetch again).
  property string gateKind: ""
  property string gateTitle: ""
  readonly property string ownGateKind: {
    if (gateKind !== "")
      return gateKind
    var n = doneNoun
    return n === "TRACK" ? "track" : n === "VIDEO" ? "video" : n === "ALBUM" ? "album" : n === "PLAYLIST" ? "playlist" : n === "MIX" ? "mix" : ""
  }
  // Opt-in for track-scoped buttons only: the ownership store is keyed by
  // exact track id, so a plain album/playlist/artist mediaId must not be
  // looked up as if it were one.
  property bool ownedCheck: false
  // Collection rollup: when set (non-null array of member track/video
  // ids), DOWNLOADED means every one of those ids is individually owned.
  // Set where the caller already has the member ids in hand (an opened
  // album/playlist/mix page, an expanded album panel), never triggers
  // a fetch itself.
  property var collectionIds: null
  // Collection rollup, discovered locally: mediaId is a collection id
  // (album/playlist/mix) and its rollup is read from what Waves has
  // already LEARNED locally (see collectionOwnership): no
  // caller-supplied list needed, so this also covers collapsed rows and
  // shelf cards that have never had their track list fetched. A
  // collection Waves has genuinely never opened or downloaded reads as
  // unknown (not owned) until the first time it is: this is a local
  // cache, not a live query, so it can never require a network call.
  property bool collectionCheck: false
  property bool owned: false
  // Optional album-level library check: when the caller supplies the
  // album's identity facts, a FULL local copy renders this button in the
  // same inert DOWNLOADED state the ownership rollup uses, so an album
  // you already have is prevented at the button itself. A PARTIAL copy
  // keeps a live Download (completing an album is not a duplicate), and
  // no facts or no scan index means no check. Display and this button's
  // own state are the ONLY consumers of the answer: the engine never
  // sees it, and every claim, album or track, keeps its click routed to
  // the gate, so a wrong tag match is always one click from downloading
  // anyway.
  //
  // The album's identity arrives as ONE object ({artist, title, year,
  // tracks}), not four properties. Four properties meant four change
  // handlers and so four QML->Python presence calls to fill one button
  // in, plus a fifth from onCompleted: measured at 15 calls per album
  // row, 750 for a 50-row page at 22us apiece, ~16ms of GUI thread spent
  // asking the same question. One property is one binding evaluation and
  // one call.
  property var libAlbum: null
  // The track twin of libAlbum ({artist, title, album, year}), for buttons
  // that download ONE song. Same economy, same one object per button.
  //
  // A track has no coverage axis: it is on disk or it is not, so a match
  // is always the done shape and libPartial can never be true here. What
  // it keeps from the album side is the part that matters, the click
  // still opens the gate, because a track match is the most brittle
  // guess this app makes (the key is the exact normalised title and
  // artist, edition qualifiers included) and a guess must never be the
  // end of the conversation. Never set for a video: the scan only ever
  // holds audio.
  property var libTrack: null
  // The artist grain: just the NAME, because the rollup
  // (artistLibraryPresence) is keyed on nothing else. The two
  // artist-wide buttons, "Download discography" on the artist page and
  // "Download artist" on a search card, were the last download controls
  // that never asked, so an artist whose whole catalogue was already on
  // disk still offered a plain DOWNLOAD.
  //
  // It is a second crossing on a surface whose ArtistBadges strip also
  // asks, and deliberately so: the budget this app keeps is one call per
  // thing that ASKS, not one per row (see tests/ui/test_presence_call_budget
  // and the track row, whose pill and button both count). The rollup
  // itself is derived once and cached per index, so the repeat is a
  // dict.get behind the crossing.
  //
  // Ownership cannot stand in for it: ownedCheck looks its mediaId up as
  // a TRACK id, and an artist id is not one.
  property string libArtist: ""
  // Kept as a derived read for the Connections guard below (and so a test
  // can find a button by the album or track it is showing). The artist
  // grain is deliberately NOT folded in: it has no title, it can never
  // reach the claim gate that reads this, and an artist button counted
  // as an album consumer would loosen the album call budget by a whole
  // page of cards.
  readonly property string libTitle: {
    if (libAlbum && libAlbum.title)
      return "" + libAlbum.title
    if (libTrack && libTrack.title)
      return "" + libTrack.title
    return ""
  }
  property bool libPresent: false
  // The scan matched this album but not all of it (some tracks are on
  // disk, some are not): the button stays an action, in cyan, and a
  // click downloads normally, which with the bulk claim gate on fetches
  // only the missing tracks.
  property bool libPartial: false
  // The identity axis of the verdict (presence "sure"): the match was
  // proven by year and edition title, not just the key. A sure claim
  // wears the same green IN LIBRARY as the fact tier (the state is the
  // colour); gold MAYBE is reserved for unproven matches. What green
  // claim keeps that owned green lacks: the click still opens the gate.
  property bool libSure: false
  // The matched local folder, carried so the click-through can name it
  // and reveal it (see libraryClaimGate).
  property string libPath: ""
  property bool _libResolved: false
  function refreshLibPresent() {
    _libResolved = true
    var a = db.libAlbum
    if (!a || !a.title) {
      var t = db.libTrack
      if (!t || !t.title) {
        if (db.libArtist === "") {
          libPresent = false
          libPartial = false
          libSure = false
          libPath = ""
          return
        }
        // The artist grain. A discography has no completeness
        // axis: nobody, this app least of all, can say what "all
        // of it" is, so the rollup can only ever reach the PARTIAL
        // face, a still-live download button coloured to say part
        // of this is already here. Reporting it as present + full
        // would make an inert DOWNLOADED out of a question that
        // has no answer, and there is no single folder to reveal,
        // so an artist button never opens the claim gate either.
        var ap = waves.artistLibraryPresence(db.libArtist)
        libPresent = false
        libPartial = !!(ap && ap.present === true)
        libSure = false
        libPath = ""
        return
      }
      var tp = waves.libraryTrackPresence("" + (t.artist || ""), "" + t.title, "" + (t.album || ""), "" + (t.year || ""), t.duration_sec || 0);
      // No completeness bar to apply: presence alone is the done
      // shape, and identity alone picks green from gold.
      libPresent = !!(tp && tp.present === true)
      libPartial = false
      libSure = !!(tp && tp.sure === true)
      libPath = libPresent ? ("" + (tp.local_album_id || "")) : ""
      return
    }
    var p = waves.libraryAlbumPresence("" + (a.artist || ""), "" + a.title, "" + (a.year || ""), a.tracks || 0, a.duration_sec || 0);
    // Coverage picks the shape (gold claim vs cyan partial), identity
    // picks the gold wording: an apparently complete but unproven
    // match is exactly what MAYBE is for, while a copy short on
    // tracks is partial no matter how proven.
    libPresent = !!(p && p.present === true && p.full === true)
    libPartial = !!(p && p.present === true && p.full !== true)
    libSure = !!(p && p.sure === true)
    libPath = libPresent ? ("" + (p.local_album_id || "")) : ""
  }
  // DOWNLOADED purely because the library scan matched something on disk:
  // a GUESS from tags, not a record of a download Waves made. Ownership
  // (`owned`) is a fact and stays inert; this one keeps a way through,
  // because a wrong match must never be the end of the conversation.
  readonly property bool libClaim: liveSt === "" && !owned && libPresent
  // The gold face of a claim: only the UNPROVEN ones. A sure claim falls
  // through to the green done styling below (state is the colour) while
  // libClaim keeps routing its click to the gate.
  readonly property bool libGuess: libClaim && !libSure
  // The partial twin: informative colour on a still-live button. Never
  // true alongside libClaim (present is either full or partial).
  readonly property bool libPartialClaim: liveSt === "" && !owned && libPartial
  // The click-through itself: explain the claim, show where the copy is,
  // and leave DOWNLOAD ANYWAY one click away. A function rather than
  // inline in the MouseArea so the scenario test can drive it.
  function openLibraryClaim() {
    host.openLibraryClaim(db.mediaId, db.libTitle, db.libPath, db.libAlbum ? "album" : "track")
  }
  // The owned twin: a record of a download Waves made. The gate names its
  // folder and offers REDOWNLOAD, so a copy Waves wrote is never a dead end.
  readonly property bool canRedownload: liveSt === "" && owned && ownGateKind !== "" && mediaId !== ""
  function openRedownload() {
    host.openRedownloadGate({
      kind: db.ownGateKind,
      id: db.mediaId,
      title: db.gateTitle !== "" ? db.gateTitle : db.libTitle
    }, db.ownFolder)
  }
  // "pending" = at least one member's ownership has never been answered
  // this session (the cache is cold and a worker is fetching); a single
  // firm "not owned" settles the rollup to false no matter what is
  // still in flight. The button holds its roll animation on pending so
  // the answer landing a beat later snaps in instead of visibly
  // flipping a face that was never true.
  // The bridge answers the whole rollup in one call (see
  // collectionOwnership): "owned" / "pending" / "no".
  function _rollupWord(v) {
    return v === "owned" ? true : v === "pending" ? "pending" : false
  }
  property bool ownPending: false
  // collectionCheck mode's member ids, cached so the ownership listener
  // can ignore other collections' answers (see the ArtCard twin).
  property var _ownIds: null
  // Batch keys for the ids this button answers for (host.ownKeys).
  property var _ownKeys: null
  function refreshOwned() {
    var r
    if (collectionIds !== null) {
      _ownKeys = host.ownKeys(collectionIds)
      var cd = waves.collectionOwnershipDetail(collectionIds)
      r = _rollupWord(cd ? cd.verdict : "no")
      ownInLibrary = !!(cd && cd.in_library === true)
      ownFolder = cd && cd.folder ? "" + cd.folder : ""
    } else if (collectionCheck && mediaId !== "") {
      var co = waves.collectionOwnership(mediaId)
      _ownIds = co ? co.ids : null
      _ownKeys = host.ownKeys(_ownIds)
      r = _rollupWord(co ? co.verdict : "no")
      ownInLibrary = !!(co && co.in_library === true)
      ownFolder = co && co.folder ? "" + co.folder : ""
    } else {
      _ownKeys = ownedCheck && mediaId !== "" ? ["," + mediaId + ","] : null
      var o = ownedCheck && mediaId !== "" ? waves.ownershipOf(mediaId) : ({})
      r = o.pending === true ? "pending" : (o.owned === true && o.up_to_date === true)
      ownInLibrary = o.in_library === true
      ownFolder = o.folder ? "" + o.folder : ""
    }
    ownPending = (r === "pending")
    owned = (r === true)
  }
  onOwnPendingChanged: if (!ownPending && !rollReady) {
    syncGhost()
    dbSettle.restart()
  }
  // Only if the libAlbum binding has not already answered: an
  // unconditional resolve here is exactly the extra call this shape
  // exists to avoid.
  // rollReady only once the ownership answer is real: a cold cache
  // answers "pending" and the truth lands a beat later; arming the roll
  // then would animate a flip the user reads as every button changing
  // its mind.
  Component.onCompleted: {
    refreshOwned()
    if (!_libResolved)
      refreshLibPresent()
    syncGhost()
    if (!ownPending)
      rollReady = true
  }
  onMediaIdChanged: {
    if (rollReady) {
      rollReady = false
      dbSettle.restart()
    }
    refreshOwned()
  }
  onOwnedCheckChanged: refreshOwned()
  onCollectionIdsChanged: refreshOwned()
  onCollectionCheckChanged: refreshOwned()
  onLibAlbumChanged: refreshLibPresent()
  onLibTrackChanged: refreshLibPresent()
  onLibArtistChanged: refreshLibPresent()
  Connections {
    target: waves
    enabled: db.libTitle !== "" || db.libArtist !== ""
    function onLibraryPresenceChanged() {
      db.refreshLibPresent()
    }
  }
  Connections {
    target: waves
    enabled: db.ownedCheck || db.collectionIds !== null || db.collectionCheck
    // Empty id = broadcast (the quality setting changed).
    function onOwnershipChanged(tid) {
      if (db.collectionIds !== null) {
        if (tid === "" || db.collectionIds.indexOf(tid) !== -1)
          db.refreshOwned()
      } else if (db.collectionCheck) {
        if (tid === "" || (db._ownIds && db._ownIds.indexOf(tid) !== -1))
          db.refreshOwned()
      } else if (tid === db.mediaId || tid === "") {
        db.refreshOwned()
      }
    }
    function onOwnershipChangedBatch(batch) {
      if (host.ownBatchHits(batch, db._ownKeys))
        db.refreshOwned()
    }
    function onCollectionMembershipChanged(cid) {
      if (db.collectionCheck && cid === db.mediaId)
        db.refreshOwned()
    }
  }
  readonly property real pct: host.dlPct(mediaId)
  readonly property string liveSt: host.dlSt(mediaId)
  readonly property string st: liveSt !== "" ? liveSt : ((owned || libPresent) ? "done" : "")
  // "preparing" = the click is parked behind a prerequisite (a metadata
  // re-fetch, a folder-tree warm, an edition scan) and has not reached the
  // queue yet. It draws exactly like queued, so the hand-over to a real
  // queue row is the cancel ✕ fading in and nothing else moving. It used
  // to draw as "running", which flashed a progress bar for a download that
  // had not started and then snapped to the queued pill.
  readonly property bool waiting: st === "queued" || st === "preparing"
  implicitHeight: dbRow.implicitHeight + btnPadV * 2
  // Width is pinned to the idle label ("⭳ DOWNLOAD …") so the button
  // doesn't shrink when the state text changes to DONE/RETRY, keeps
  // row columns aligned and avoids layout jumps mid-download.
  implicitWidth: Math.max(dbRow.implicitWidth, dbMetric.implicitWidth, dbMetricDone.implicitWidth, dbMetricQueued.implicitWidth, (db.libAlbum || db.libArtist !== "") ? dbMetricLib.implicitWidth : db.libTrack ? dbMetricLibTrack.implicitWidth : 0) + btnPadH * 2 + (db.showChooser ? 28 : 0)
  Row {
    id: dbMetric
    visible: false
    spacing: 7
    Ico {
      name: "arrow-down"
      color: accent
      size: 14
      bold: 10
    }
    Text {
      textFormat: Text.PlainText
      text: db.label.toUpperCase()
      font.family: uiFont
      font.pixelSize: 11
      font.bold: true
      font.letterSpacing: btnTrack
    }
  }
  Row {
    id: dbMetricDone
    visible: false
    spacing: 7
    Ico {
      name: "check"
      color: accent
      size: 14
    }
    Text {
      textFormat: Text.PlainText
      text: (db.doneNoun !== "" ? db.doneNoun + " " : "") + (host.libraryOn && (db.libPresent || (db.owned ? db.ownInLibrary : host.dlInLibrary)) ? "IN LIBRARY" : "DOWNLOADED")
      font.family: uiFont
      font.pixelSize: 11
      font.bold: true
      font.letterSpacing: btnTrack
    }
  }
  // The longest library-claim label ("PARTIALLY IN LIBRARY" beats "MAYBE
  // IN LIBRARY") is measured for the same reason DOWNLOADED is: the
  // width must not move when a claim resolves, or one matched album in a
  // list would shunt its own row's button out of line with every
  // neighbour. Counted for the buttons that can reach the partial face,
  // album and artist, since a track button can never reach either state
  // and must not reserve width for them.
  Row {
    id: dbMetricLib
    visible: false
    spacing: 7
    Ico {
      name: "check"
      color: accent
      size: 14
    }
    Text {
      textFormat: Text.PlainText
      text: "PARTIALLY IN LIBRARY"
      font.family: uiFont
      font.pixelSize: 11
      font.bold: true
      font.letterSpacing: btnTrack
    }
  }
  // The track twin. A track can reach only two claim faces, MAYBE IN
  // LIBRARY and the done label, and the done label is already measured
  // above (dbMetricDone spells the noun out), so the hedge is the one
  // width left to reserve. Kept separate from dbMetricLib because
  // PARTIALLY is a word a track button can never say, and reserving for
  // it would pad every track row in the app.
  Row {
    id: dbMetricLibTrack
    visible: false
    spacing: 7
    Ico {
      name: "check"
      color: accent
      size: 14
    }
    Text {
      textFormat: Text.PlainText
      text: "MAYBE IN LIBRARY"
      font.family: uiFont
      font.pixelSize: 11
      font.bold: true
      font.letterSpacing: btnTrack
    }
  }
  // Queued measures too, now that it carries a cancel X: without it the
  // button grew the moment a click was queued, and in a track list every
  // row's button is aligned against its neighbours'. Boxes, not the real
  // glyphs: a QueueStack and an Ico per idle row would be three bars and
  // a vector path built for a state the row is almost never in.
  Row {
    id: dbMetricQueued
    visible: false
    spacing: 7
    Item {
      width: 12
      height: 12
    }      // QueueStack, default barW
    Text {
      textFormat: Text.PlainText
      text: db.queuedLabel
      font.family: uiFont
      font.pixelSize: 11
      font.bold: true
      font.letterSpacing: btnTrack
    }
    Item {
      width: 13
      height: 13
    }      // the cancel X
  }
  radius: btnRad
  // Inside a RollSwap the outline is the wrapper's; see PreviewBar.bare.
  property bool bare: false
  // Filled like DOWNLOAD SELECTED so every download button reads primary.
  // A library claim wears gold, not green: green DOWNLOADED is a fact
  // (Waves wrote that exact file), gold IN LIBRARY is a tag match, a
  // guess that stays clickable to explain itself.
  // A partial claim wears cyan: still a live download button (a click
  // fetches what's missing), coloured to say part of this is on disk.
  readonly property color fill: libGuess ? goldCont : libPartialClaim ? cyanCont : st === "done" ? greenCont : st === "failed" ? redCont : accentCont
  readonly property color edge: libGuess ? goldDim : libPartialClaim ? cyanDim : st === "done" ? greenDim : st === "failed" ? red : accentDim
  // Bare = inside a RollSwap, where the pill draws BOTH fill and outline
  // (it takes `fill` through liveColor). Painting the fill here too laid
  // an opaque rectangle over the pill's own border ring (Qt draws a
  // border inside the item's bounds), so on the Browse cards the running
  // bar lost its green edge and kept only a ragged sliver of it at the
  // corners, where this rectangle's antialiased corner let it through.
  color: bare ? "transparent" : fill
  border.width: bare ? 0 : btnBorderW
  border.color: edge
  // State changes FADE between colours instead of snapping: queued ->
  // running -> done reads as one button changing its mind, not three
  // buttons taking turns. 420ms InOutQuad, paced to land just after
  // the 340ms state roll below so the hue settles as the new face
  // does; symmetric easing because OutCubic spends its travel in the
  // first frames and reads as a snap on these near-black fills.
  // Instant with motion off, same gate as the other control animation.
  Behavior on color {
    ColorAnimation {
      duration: host.hoverMotion ? 420 : 0
      easing.type: Easing.InOutQuad
    }
  }
  Behavior on border.color {
    ColorAnimation {
      duration: host.hoverMotion ? 420 : 0
      easing.type: Easing.InOutQuad
    }
  }
  clip: true
  scale: 1
  Behavior on scale {
    NumberAnimation {
      duration: 130
      easing.type: Easing.OutBack
    }
  }

  // RUNNING, the dot matrix fills the whole button, edge to edge, five
  // rows dense; the percentage is carved into it while hovered (see
  // DotMatrix.word). A bar that stopped 12px in, with a "NN%" readout
  // to its right in a slot reserved for "100%", would leave a
  // two-character hole beside a short number for most of a run.
  // Behind a Loader rather than plain `visible: false`: an invisible
  // subtree is still BUILT, and this one is a 200-dot matrix. A row that
  // is not downloading has no progress to draw, but building it for
  // every row of a 500-track playlist costs 92 of the 232 items a
  // TrackRow creates (measured). The Loader has a size, so the loaded
  // Item is sized to it (no anchors needed inside).
  // The percentage shows while the pointer is over the button, or over
  // whatever the caller names (a Browse card passes its whole art, the
  // way its controls already rise for the card, not the pill).
  property bool wordHover: dbHover.hovered
  Loader {
    // The matrix rides the same state roll as the label faces: it
    // arrives from below when a run starts (while the queued face
    // exits above) and leaves through the top when the run ends.
    // Kept active until its own exit lands, or the end of a run would
    // unload 200 bright dots in a single frame.
    active: db.st === "running" || opacity > 0
    // Inside the 1px outline: the grid runs to it and its outer
    // cells fade (edgeFadeW / H below), so nothing meets the border
    // hard and the corner cells vanish under the radius.
    anchors.fill: parent
    anchors.leftMargin: 1
    anchors.rightMargin: 1
    // The exit belt is taken ONLY when this roll is the matrix's own
    // exit (matrixRollOut, set when the state leaves "running"). Every
    // other roll is a label swap between two text faces, and riding
    // rollOut unconditionally put a progress matrix on the way out of
    // rolls that never ran: a click from idle to queued flashed one,
    // and so did every button whose library claim resolved late.
    opacity: db.st === "running" ? db.rollIn : (db.matrixRollOut ? db.rollOut : 0)
    transform: Translate {
      y: db.st === "running" ? 10 * (1 - db.rollIn) : -10 * (1 - db.rollOut)
    }
    sourceComponent: Item {
      // Nothing sits beside the matrix: its width IS the item's, so
      // no digit landing can ever reflow it (the case the
      // stable-width test guards).
      DotMatrix {
        objectName: "dbMatrix"
        ledPulse: host.ledPulse
        shimmerPhase: host.shimmerPhase
        queueEdgeHeld: host.queueEdgeHeld
        anchors.left: parent.left
        anchors.right: parent.right
        // Centred to the DEVICE pixel, not the logical one: the
        // grid is 27px in a 28px button, an offset of 0.5, which
        // is a whole pixel at 2x. Rounding to a logical pixel
        // would sit the bar a pixel low on every retina display,
        // and an anchor centre would leave it on a half pixel
        // at 1x.
        y: Math.round((parent.height - implicitHeight) / 2 * Screen.devicePixelRatio) / Screen.devicePixelRatio
        // Seven rows of 3px cells with 1px gaps fill the button
        // top to bottom; the outer cells fade toward every edge
        // (26px at the ends, 8px top and bottom, the shelf fades'
        // curve) so the field sits in a soft frame inside the
        // outline.
        rows: 7
        dot: 3
        gap: 1
        pct: Math.max(0, db.pct)
        edgeFadeW: 26
        edgeFadeH: 8
        // The two outer columns are pads that mirror the fill's
        // edge: the first real block lights two columns in, where
        // the fade is at 36% and the next at 60%, instead of under
        // it. Rows are not padded and no more columns are: four
        // pad columns plus pad rows would start the fill several
        // blocks to the right of the start.
        padCols: 2
        mirrorPads: true
        // Only loaded while st === "running", so 100% here means the
        // final steps are still in flight: twinkle in step with the
        // queue row for the same item.
        finishing: db.pct >= 99.9
        // pct is -1 until the first progress event: no word then
        // (the bar alone says "starting"; there is no reading to
        // spell yet).
        word: db.pct >= 0 ? Math.round(db.pct) + "%" : ""
        // 460ms both ways (the dissolve wants longer than a plain
        // fade to read as one), instant with motion off. One value
        // drives every cell, so leaving mid-reveal reverses from
        // wherever it is.
        wordReveal: db.wordHover ? 1 : 0
        Behavior on wordReveal {
          NumberAnimation {
            duration: host.hoverMotion ? 460 : 0
            easing.type: Easing.InOutSine
          }
        }
      }
    }
  }
  // IDLE / QUEUED / DONE / FAILED, centered glyph + label
  // Queued: the click is in the queue but no download slot has picked
  // it up yet; the stack glyph's walking highlight says the wait is
  // alive, and the label keeps the media noun ("QUEUED ALBUM").
  readonly property string queuedLabel: "QUEUED" + label.toUpperCase().replace("DOWNLOAD", "")
  // The state roll: RollSwap's belt, transplanted onto the button's
  // own face changes. When the label text changes (the one reliable
  // tell that the face did), the OLD face rides out the top while the
  // new one arrives from the bottom, on RollSwap's no-overlap curve
  // (exit ends at 0.44, entry starts there). The ghost row shows the
  // last COMMITTED face (icon + label snapshot, resynced when the roll
  // lands), so mid-roll both faces are real pixels, not a text pop.
  property real rollT: 1
  readonly property real rollOut: 1 - Math.min(1, rollT / 0.44)
  readonly property real rollIn: Math.max(0, (rollT - 0.44) / 0.56)
  property string ghostIco: ""
  property color ghostIcoColor: accent
  property string ghostText: ""
  property color ghostTextColor: accent
  property bool rollReady: false
  // Rebinding is not news: a recycled list delegate (reuseItems) hands
  // this button the next row's identity, and the face swap that follows
  // must land settled, not ride the belt, exactly the pills' settleKey
  // rule (see LibraryTag). mediaId is what the button is currently
  // about, so its change drops the latch; the 0-interval re-arm
  // restores it once the rebind's own property changes have landed.
  Timer {
    id: dbSettle
    interval: 0
    onTriggered: db.rollReady = true
  }
  // Whether THIS roll is the matrix's own exit (a run just ended). It
  // picks which of the two outgoing faces rides the belt: the matrix
  // takes it and the ghost sits out, since two things leaving through
  // the top would double up. False for every label-only swap, or an
  // idle button would flash a progress matrix it never earned.
  property bool matrixRollOut: false
  property string _prevSt: ""
  onStChanged: {
    var was = _prevSt
    _prevSt = st
    if (!rollReady)
      return
    if (st === "running") {
      matrixRollOut = false
      startRoll()
    } else {
      matrixRollOut = (was === "running")
      if (matrixRollOut)
        startRoll()
    }
  }
  function syncGhost() {
    ghostIco = (db.st !== "failed" && !db.waiting && db.st !== "running") ? dbFaceIco.name : ""
    ghostIcoColor = dbFaceIco.color
    ghostText = dbFaceText.text
    ghostTextColor = dbFaceText.color
  }
  function startRoll() {
    rollAnim.stop()
    rollT = 0
    rollAnim.start()
  }
  NumberAnimation {
    id: rollAnim
    target: db
    property: "rollT"
    to: 1
    duration: host.hoverMotion ? 340 : 0
    easing.type: Easing.OutCubic
    onStopped: db.syncGhost()
  }
  // The outgoing face. No input, no loaders: a still image of what the
  // button just stopped saying, on its way out through the top.
  Row {
    id: dbGhost
    spacing: 7
    anchors.centerIn: parent
    anchors.verticalCenterOffset: -10 * (1 - db.rollOut)
    opacity: db.rollOut
    // The matrix takes the exit belt itself both into and out of a
    // run; the ghost would ride alongside showing a stale face.
    visible: opacity > 0 && db.st !== "running" && !db.matrixRollOut
    z: 1
    Ico {
      visible: db.ghostIco !== ""
      name: db.ghostIco || "arrow-down"
      color: db.ghostIcoColor
      size: 14
      bold: db.ghostIco === "check" ? 0 : 10
      anchors.verticalCenter: parent.verticalCenter
    }
    Text {
      textFormat: Text.PlainText
      text: db.ghostText
      color: db.ghostTextColor
      font.family: uiFont
      font.pixelSize: 11
      font.bold: true
      font.letterSpacing: btnTrack
      anchors.verticalCenter: parent.verticalCenter
    }
  }
  Row {
    id: dbRow
    anchors.centerIn: parent
    spacing: 7
    // Normally the incoming face (from below, as the ghost leaves
    // above). While a run starts it swaps roles: the frozen queued
    // face is the OUTGOING one, exiting above as the matrix arrives.
    anchors.verticalCenterOffset: db.st === "running" ? -10 * (1 - db.rollOut) : 10 * (1 - db.rollIn)
    opacity: db.st === "running" ? db.rollOut : db.rollIn
    visible: opacity > 0
    // Above the button-wide MouseArea declared below, which would
    // otherwise swallow every press aimed at the cancel X. Nothing
    // else in here takes input, so raising the row costs no clicks.
    z: 1
    Ico {
      id: dbFaceIco
      visible: db.st !== "failed" && !db.waiting && db.st !== "running"
      name: db.st === "done" ? "check" : "arrow-down"
      color: db.libGuess ? gold : db.libPartialClaim ? cyan : accent
      Behavior on color {
        ColorAnimation {
          duration: host.hoverMotion ? 420 : 0
          easing.type: Easing.InOutQuad
        }
      }
      size: 14
      bold: db.st === "done" ? 0 : 10
      anchors.verticalCenter: parent.verticalCenter
    }
    // Both draw through a Canvas, and both belong to a state a row is
    // almost never in. Same reason as the dot matrix above: gate them
    // on `active`, not `visible`, so an idle row builds neither.
    // `visible: active` matters: a Row skips invisible children but
    // still spaces around a zero-width one, so an inactive Loader left
    // visible would pad the idle button by two gaps.
    Loader {
      // Held through "running" too: the queued face rides the exit
      // belt as the matrix arrives, and unloading the stack glyph at
      // the waiting flip would snap it out one frame into that roll.
      active: db.waiting || db.st === "running"
      visible: active
      anchors.verticalCenter: parent.verticalCenter
      sourceComponent: QueueStack {
        marchTick: host.marchTick
      }
    }
    Loader {
      active: db.st === "failed"
      visible: active
      anchors.verticalCenter: parent.verticalCenter
      sourceComponent: RetryMark {
        color: red
        box: 16
      }
    }
    Text {
      id: dbFaceText
      // Named so the scenario test can read the WORDS the user sees,
      // not just the properties that are supposed to pick them.
      objectName: "dbFaceText"
      // The face's one reliable change tell: every state lands with
      // its own words, so a text change IS a face change, and the
      // roll rides it. Guarded until the first commit so creation
      // does not roll.
      //
      // Skipped while a roll is already running, because then the
      // state handler started it and owns matrixRollOut: without the
      // guard, a state change that also changes the words (every run
      // ending) restarted its own roll here and cancelled the
      // matrix's exit. When no roll is in flight the change is a
      // label-only swap, which clears the flag rather than inheriting
      // whatever the last state change left in it.
      onTextChanged: if (db.rollReady && !rollAnim.running) {
        db.matrixRollOut = false
        db.startRoll()
      }
      textFormat: Text.PlainText  // db.label carries a remote artist name
      // The claim says what it knows, never what the fact-state says
      // ("DOWNLOADED"): the scan matched tags on disk, it did not
      // watch Waves write the file. It says MAYBE out loud, because
      // this button is where a guess PREVENTS an action, and the
      // hedge is the difference between "we recorded this" and "we
      // recognised this". The gold stays: colour separates it from
      // green DOWNLOADED, the word explains why they differ.
      // With the library scan on, the done state reads IN LIBRARY
      // instead of DOWNLOADED, but only when the library actually
      // holds the copy: the scan proved it present (libPresent), the
      // recorded copy itself sits under the library root
      // (ownInLibrary), or, for a download that just finished and
      // has no record read yet, downloads land inside the root
      // (dlInLibrary). A copy OUTSIDE the library stays DOWNLOADED,
      // wherever downloads go today; move the files in and the
      // rescan flips the word. Green still marks a recorded fact (gold MAYBE
      // and cyan PARTIALLY are the guesses).
      // "running" keeps the queued face frozen: the row is riding the
      // exit belt as the matrix arrives, and letting the text fall
      // through to the idle label would restart the roll mid-exit.
      text: db.libGuess ? "MAYBE IN LIBRARY" : db.st === "done" ? ((db.doneNoun !== "" ? db.doneNoun + " " : "") + (host.libraryOn && (db.libPresent || (db.owned ? db.ownInLibrary : host.dlInLibrary)) ? "IN LIBRARY" : "DOWNLOADED")) : db.st === "failed" ? "RETRY" : (db.waiting || db.st === "running") ? db.queuedLabel : db.libPartialClaim ? "PARTIALLY IN LIBRARY" : db.label.toUpperCase()
      color: db.libGuess ? gold : db.st === "done" ? accent : db.st === "failed" ? red : (db.waiting || db.st === "running") ? accentDim : db.libPartialClaim ? cyan : accent
      Behavior on color {
        ColorAnimation {
          duration: host.hoverMotion ? 420 : 0
          easing.type: Easing.InOutQuad
        }
      }
      font.family: uiFont
      font.pixelSize: 11
      font.bold: true
      font.letterSpacing: btnTrack
      anchors.verticalCenter: parent.verticalCenter
    }
    // Queued only: give up the wait right here, instead of opening the
    // queue drawer to find the same row. Its own click zone, because
    // the button around it is deliberately inert while queued.
    // Loaded for "preparing" too, holding its space blank and inert:
    // there is no queue row to cancel yet, and reserving the width means
    // the label doesn't shift sideways when the row lands and the ✕
    // fades in.
    Loader {
      // Same hold as the stack glyph: alive through the queued face's
      // exit under the matrix (the X itself already fades via its
      // own opacity the moment st leaves "queued").
      active: db.waiting || db.st === "running"
      visible: active
      anchors.verticalCenter: parent.verticalCenter
      sourceComponent: Ico {
        // Red at rest, brighter on hover: the same read as the
        // player's stop glyph, and the only way out of a queued
        // click should not have to be hunted for.
        name: "close"
        size: 13
        bold: 8
        color: dbCancelMa.containsMouse ? "#ff7d76" : red
        opacity: db.st === "queued" ? 1 : 0
        Behavior on opacity {
          NumberAnimation {
            duration: 160
            easing.type: Easing.OutCubic
          }
        }
        MouseArea {
          id: dbCancelMa
          anchors.fill: parent
          anchors.margins: -5
          enabled: db.st === "queued"
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: function (m) {
            m.accepted = true
            host.cancelQueuedMedia(db.mediaId)
          }
        }
      }
    }
  }
  MouseArea {
    // Named so the scenario test can drive the REAL tap area rather
    // than the functions behind it (the wiring is the thing at risk).
    objectName: "dbTapArea"
    anchors.fill: parent
    anchors.rightMargin: db.showChooser ? 28 : 0
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    onPressed: function (m) {
      if (!m || m.button === Qt.LeftButton)
        db.scale = 0.96
    }
    onReleased: db.scale = 1.0
    onCanceled: db.scale = 1.0
    onClicked: function (m) {
      // m is null when the signal is emitted programmatically
      // (the scenario tests drive this tap area directly); treat
      // that as a plain left click, the pre-Chooser behavior.
      if (m && m.button === Qt.RightButton) {
        db.openChooser()
        return
      }
      db.activate()
    }
  }
  // The chevron face: drawn exactly when the row's control carries the
  // Chooser (the bridge's capability verdict), so it exists on a
  // TIDAL-only install and never on a provider without per-click
  // options.
  Rectangle {
    id: dbChev
    visible: db.showChooser
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    width: 28
    radius: btnRad
    color: "transparent"
    border.width: 0
    Rectangle {
      anchors.left: parent.left
      anchors.top: parent.top
      anchors.bottom: parent.bottom
      width: 1
      color: db.edge
      opacity: 0.6
    }
    ExpandChevron {
      tile: 16
      glyph: 11
      showTile: false
      stroke: accent
      open: db.chooserOpen
      anchors.centerIn: parent
    }
    MouseArea {
      objectName: "dbChooserTap"
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      acceptedButtons: Qt.LeftButton | Qt.RightButton
      onClicked: db.openChooser()
    }
  }
  // The keyboard focus ring (a custom Rectangle draws none): the accent
  // outline over whatever the state frame currently paints.
  Rectangle {
    anchors.fill: parent
    radius: btnRad
    color: "transparent"
    border.width: 2
    border.color: accent
    visible: db.activeFocus
  }
  Loader {
    id: chooserLoader
    active: db.chooserBuilt
    sourceComponent: chooserComp
  }
  Component {
    id: chooserComp
    Popup {
      id: chooserPop
      objectName: "chooserPopover"
      parent: db
      // Right edge aligned with the control, and clamped inside the
      // window: the popover is wider than the download button.
      x: db.width - width
      y: db.height + 4
      margins: 8
      width: 320
      padding: 12
      modal: false
      focus: true
      closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
      // Focus the popover's own scope on open: Tab then walks its
      // rows in draw order, and Escape closes from anywhere in it.
      onOpened: contentItem.forceActiveFocus()
      background: Rectangle {
        radius: 10
        color: surfaceHi
        border.color: outline
      }
      contentItem: Column {
        spacing: 10
        Text {
          textFormat: Text.PlainText
          text: "DOWNLOAD WITH"
          color: textDim
          font.family: uiFont
          font.pixelSize: 10
          font.bold: true
          font.letterSpacing: 1
        }
        Column {
          visible: db.chooserProviders.length > 0
          spacing: 4
          Text {
            textFormat: Text.PlainText
            text: "PROVIDER"
            color: textDim
            font.family: mono
            font.pixelSize: 9
          }
          Flow {
            spacing: 6
            width: 296
            // One tile per enabled provider, straight from the
            // bridge: fixed to the row's provider
            // in v1, and the row's own tile always present. No
            // provider id, name or asset path lives in QML, so
            // a third provider renders with no edit here (the
            // Flow wraps however many arrive).
            Repeater {
              model: db.chooserProviders
              delegate: Rectangle {
                required property var modelData
                width: 140
                height: 26
                radius: 6
                color: modelData.selected ? accentCont : surface3
                border.color: modelData.selected ? accentDim : outline
                border.width: 1
                Row {
                  anchors.centerIn: parent
                  spacing: 6
                  Image {
                    visible: ("" + (modelData.logo || "")) !== ""
                    anchors.verticalCenter: parent.verticalCenter
                    source: "" + (modelData.logo || "")
                    width: modelData.logo_width > 0 ? modelData.logo_width : 16
                    height: 14
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    cache: true
                  }
                  Text {
                    textFormat: Text.PlainText
                    text: ("" + (modelData.name || modelData.id)).toUpperCase()
                    color: modelData.selected ? accentContTx : textLo
                    font.family: uiFont
                    font.pixelSize: 10
                    font.bold: true
                    anchors.verticalCenter: parent.verticalCenter
                  }
                }
                MouseArea {
                  anchors.fill: parent
                  enabled: false
                  cursorShape: Qt.PointingHandCursor
                }
              }
            }
          }
        }
        Column {
          visible: db.chooserTiers.length > 0
          spacing: 4
          Text {
            textFormat: Text.PlainText
            text: "AUDIO QUALITY"
            color: textDim
            font.family: mono
            font.pixelSize: 9
          }
          Repeater {
            model: db.chooserTiers
            delegate: Rectangle {
              id: tierRow
              objectName: "chooserTierRow"
              required property var modelData
              readonly property bool picked: ("" + modelData.word) === ("" + db.chooserTier)
              width: 296
              height: 26
              radius: 5
              color: tierRow.picked ? host.qualTint(modelData.word) : "transparent"
              border.color: tierRow.activeFocus ? accent : tierRow.picked ? host.qualBorder(modelData.word) : "transparent"
              border.width: 1
              // A picker row a keyboard or reader user can
              // take.
              activeFocusOnTab: chooserPop.visible
              Accessible.role: Accessible.RadioButton
              Accessible.name: db.chooserKind + " in " + modelData.word
              Accessible.checkable: true
              Accessible.checked: tierRow.picked
              Accessible.onPressAction: function () {
                db.chooserPickTier(modelData.word)
              }
              Keys.onReturnPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserPickTier(modelData.word)
                }
              }
              Keys.onEnterPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserPickTier(modelData.word)
                }
              }
              Keys.onSpacePressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserPickTier(modelData.word)
                }
              }
              Row {
                anchors.left: parent.left
                anchors.leftMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                Rectangle {
                  width: 6
                  height: 6
                  radius: 3
                  color: host.qualDot(modelData.word)
                  anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                  textFormat: Text.PlainText
                  text: "" + modelData.word
                  color: host.qualFg(modelData.word)
                  font.family: mono
                  font.pixelSize: 10
                  font.bold: true
                  anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                  textFormat: Text.PlainText
                  text: "" + (modelData.detail || "")
                  color: textLo
                  font.family: mono
                  font.pixelSize: 10
                  anchors.verticalCenter: parent.verticalCenter
                }
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: db.chooserPickTier(modelData.word)
              }
            }
          }
        }
        Column {
          spacing: 4
          Text {
            textFormat: Text.PlainText
            text: "AUDIO TYPE"
            color: textDim
            font.family: mono
            font.pixelSize: 9
          }
          Text {
            visible: db.chooserAtmosOnly
            textFormat: Text.PlainText
            text: "ATMOS ONLY"
            color: textHi
            font.family: mono
            font.pixelSize: 10
            font.bold: true
          }
          Row {
            visible: !db.chooserAtmosOnly
            spacing: 6
            // The provider's own words: a
            // stereo-only provider offers one option, however
            // many the Chooser would carry elsewhere.
            Repeater {
              model: db.chooserAudioOptions
              delegate: Rectangle {
                id: audioTile
                objectName: "chooserAudioTile"
                required property string modelData
                readonly property bool picked: db.chooserAudio === modelData
                width: 94
                height: 26
                radius: 6
                color: audioTile.picked ? accentCont : surface3
                border.color: audioTile.activeFocus ? accent : audioTile.picked ? accentDim : outline
                border.width: 1
                activeFocusOnTab: chooserPop.visible
                Accessible.role: Accessible.RadioButton
                Accessible.name: "Audio type: " + modelData.toUpperCase()
                Accessible.checkable: true
                Accessible.checked: audioTile.picked
                Accessible.onPressAction: function () {
                  db.chooserPickAudio(modelData)
                }
                Keys.onReturnPressed: function (event) {
                  if (!event.isAutoRepeat) {
                    event.accepted = true
                    db.chooserPickAudio(modelData)
                  }
                }
                Keys.onEnterPressed: function (event) {
                  if (!event.isAutoRepeat) {
                    event.accepted = true
                    db.chooserPickAudio(modelData)
                  }
                }
                Keys.onSpacePressed: function (event) {
                  if (!event.isAutoRepeat) {
                    event.accepted = true
                    db.chooserPickAudio(modelData)
                  }
                }
                Text {
                  textFormat: Text.PlainText
                  text: modelData.toUpperCase()
                  color: audioTile.picked ? accentContTx : textLo
                  font.family: uiFont
                  font.pixelSize: 10
                  font.bold: true
                  anchors.centerIn: parent
                }
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: db.chooserPickAudio(modelData)
                }
              }
            }
          }
        }
        Column {
          visible: db.chooserShowLyrics
          spacing: 4
          Text {
            textFormat: Text.PlainText
            text: "LYRICS"
            color: textDim
            font.family: mono
            font.pixelSize: 9
          }
          Row {
            spacing: 8
            Rectangle {
              id: lyricsEmbedTile
              objectName: "chooserLyricsEmbed"
              width: 90
              height: 24
              radius: 5
              color: db.chooserLyricsEmbed ? accentCont : surface3
              border.color: lyricsEmbedTile.activeFocus ? accent : db.chooserLyricsEmbed ? accentDim : outline
              border.width: 1
              activeFocusOnTab: chooserPop.visible
              Accessible.role: Accessible.CheckBox
              Accessible.name: "Embed lyrics"
              Accessible.checkable: true
              Accessible.checked: db.chooserLyricsEmbed
              Accessible.onPressAction: function () {
                db.chooserToggle("lyrics_embed")
              }
              Keys.onReturnPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("lyrics_embed")
                }
              }
              Keys.onEnterPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("lyrics_embed")
                }
              }
              Keys.onSpacePressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("lyrics_embed")
                }
              }
              Text {
                textFormat: Text.PlainText
                text: db.chooserLyricsEmbed ? "EMBED ON" : "EMBED OFF"
                color: db.chooserLyricsEmbed ? accentContTx : textLo
                font.family: mono
                font.pixelSize: 9
                anchors.centerIn: parent
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: db.chooserToggle("lyrics_embed")
              }
            }
            Rectangle {
              id: lyricsLrcTile
              objectName: "chooserLyricsFile"
              width: 70
              height: 24
              radius: 5
              color: db.chooserLyricsFile ? accentCont : surface3
              border.color: lyricsLrcTile.activeFocus ? accent : db.chooserLyricsFile ? accentDim : outline
              border.width: 1
              activeFocusOnTab: chooserPop.visible
              Accessible.role: Accessible.CheckBox
              Accessible.name: "Save the .lrc lyrics file"
              Accessible.checkable: true
              Accessible.checked: db.chooserLyricsFile
              Accessible.onPressAction: function () {
                db.chooserToggle("lyrics_file")
              }
              Keys.onReturnPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("lyrics_file")
                }
              }
              Keys.onEnterPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("lyrics_file")
                }
              }
              Keys.onSpacePressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("lyrics_file")
                }
              }
              Text {
                textFormat: Text.PlainText
                text: db.chooserLyricsFile ? ".LRC ON" : ".LRC OFF"
                color: db.chooserLyricsFile ? accentContTx : textLo
                font.family: mono
                font.pixelSize: 9
                anchors.centerIn: parent
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: db.chooserToggle("lyrics_file")
              }
            }
            Rectangle {
              id: lyricsTtmlTile
              objectName: "chooserLyricsTtml"
              width: 80
              height: 24
              radius: 5
              color: db.chooserLyricsTtml ? accentCont : surface3
              border.color: lyricsTtmlTile.activeFocus ? accent : db.chooserLyricsTtml ? accentDim : outline
              border.width: 1
              opacity: db.chooserShowTtml ? 1 : 0.4
              // Enabled only where the provider serves TTML:
              // an inert tile leaves the tab order.
              activeFocusOnTab: chooserPop.visible && db.chooserShowTtml
              enabled: db.chooserShowTtml
              Accessible.role: Accessible.CheckBox
              Accessible.name: "Save the verbatim .ttml lyrics file"
              Accessible.checkable: true
              Accessible.checked: db.chooserLyricsTtml
              Accessible.onPressAction: function () {
                db.chooserToggle("lyrics_ttml_file")
              }
              Keys.onReturnPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("lyrics_ttml_file")
                }
              }
              Keys.onEnterPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("lyrics_ttml_file")
                }
              }
              Keys.onSpacePressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("lyrics_ttml_file")
                }
              }
              Text {
                textFormat: Text.PlainText
                text: db.chooserLyricsTtml ? ".TTML ON" : ".TTML OFF"
                color: db.chooserLyricsTtml ? accentContTx : textLo
                font.family: mono
                font.pixelSize: 9
                anchors.centerIn: parent
              }
              MouseArea {
                anchors.fill: parent
                enabled: db.chooserShowTtml
                cursorShape: Qt.PointingHandCursor
                onClicked: db.chooserToggle("lyrics_ttml_file")
              }
            }
          }
        }
        Column {
          visible: db.chooserShowArt
          spacing: 4
          Text {
            textFormat: Text.PlainText
            text: "ALBUM ART"
            color: textDim
            font.family: mono
            font.pixelSize: 9
          }
          Row {
            spacing: 8
            Rectangle {
              id: coverFileTile
              objectName: "chooserCoverFile"
              width: 130
              height: 24
              radius: 5
              color: db.chooserCoverFile ? accentCont : surface3
              border.color: coverFileTile.activeFocus ? accent : db.chooserCoverFile ? accentDim : outline
              border.width: 1
              activeFocusOnTab: chooserPop.visible
              Accessible.role: Accessible.CheckBox
              Accessible.name: "Save the cover as a sidecar file"
              Accessible.checkable: true
              Accessible.checked: db.chooserCoverFile
              Accessible.onPressAction: function () {
                db.chooserToggle("cover_file")
              }
              Keys.onReturnPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("cover_file")
                }
              }
              Keys.onEnterPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("cover_file")
                }
              }
              Keys.onSpacePressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("cover_file")
                }
              }
              Text {
                textFormat: Text.PlainText
                text: db.chooserCoverFile ? "SIDECAR ON" : "SIDECAR OFF"
                color: db.chooserCoverFile ? accentContTx : textLo
                font.family: mono
                font.pixelSize: 9
                anchors.centerIn: parent
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: db.chooserToggle("cover_file")
              }
            }
            Rectangle {
              id: coverEmbedTile
              objectName: "chooserCoverEmbed"
              width: 110
              height: 24
              radius: 5
              color: db.chooserCoverEmbed ? accentCont : surface3
              border.color: coverEmbedTile.activeFocus ? accent : db.chooserCoverEmbed ? accentDim : outline
              border.width: 1
              activeFocusOnTab: chooserPop.visible
              Accessible.role: Accessible.CheckBox
              Accessible.name: "Embed the cover art"
              Accessible.checkable: true
              Accessible.checked: db.chooserCoverEmbed
              Accessible.onPressAction: function () {
                db.chooserToggle("cover_embed")
              }
              Keys.onReturnPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("cover_embed")
                }
              }
              Keys.onEnterPressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("cover_embed")
                }
              }
              Keys.onSpacePressed: function (event) {
                if (!event.isAutoRepeat) {
                  event.accepted = true
                  db.chooserToggle("cover_embed")
                }
              }
              Text {
                textFormat: Text.PlainText
                text: db.chooserCoverEmbed ? "EMBED ON" : "EMBED OFF"
                color: db.chooserCoverEmbed ? accentContTx : textLo
                font.family: mono
                font.pixelSize: 9
                anchors.centerIn: parent
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: db.chooserToggle("cover_embed")
              }
            }
          }
        }
        Row {
          spacing: 8
          Rectangle {
            id: chooserDefaultsBtn
            objectName: "chooserSetDefaults"
            width: 150
            height: 30
            radius: 6
            color: "transparent"
            border.color: chooserDefaultsBtn.activeFocus ? accent : accentDim
            border.width: chooserDefaultsBtn.activeFocus ? 2 : 1
            activeFocusOnTab: chooserPop.visible
            Accessible.role: Accessible.Button
            Accessible.name: "Set as defaults"
            Accessible.onPressAction: function () {
              db.saveChooserAsDefaults()
            }
            Keys.onReturnPressed: function (event) {
              if (!event.isAutoRepeat) {
                event.accepted = true
                db.saveChooserAsDefaults()
              }
            }
            Keys.onEnterPressed: function (event) {
              if (!event.isAutoRepeat) {
                event.accepted = true
                db.saveChooserAsDefaults()
              }
            }
            Keys.onSpacePressed: function (event) {
              if (!event.isAutoRepeat) {
                event.accepted = true
                db.saveChooserAsDefaults()
              }
            }
            Text {
              textFormat: Text.PlainText
              text: "SET AS DEFAULTS"
              color: accentContTx
              font.family: uiFont
              font.pixelSize: 10
              font.bold: true
              anchors.centerIn: parent
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: db.saveChooserAsDefaults()
            }
          }
          Rectangle {
            id: chooserConfirmBtn
            objectName: "chooserConfirm"
            width: 120
            height: 30
            radius: 6
            color: accent
            border.color: chooserConfirmBtn.activeFocus ? textHi : "transparent"
            border.width: 2
            activeFocusOnTab: chooserPop.visible
            Accessible.role: Accessible.Button
            Accessible.name: "Download with these options"
            Accessible.onPressAction: function () {
              db.confirmChooser()
            }
            Keys.onReturnPressed: function (event) {
              if (!event.isAutoRepeat) {
                event.accepted = true
                db.confirmChooser()
              }
            }
            Keys.onEnterPressed: function (event) {
              if (!event.isAutoRepeat) {
                event.accepted = true
                db.confirmChooser()
              }
            }
            Keys.onSpacePressed: function (event) {
              if (!event.isAutoRepeat) {
                event.accepted = true
                db.confirmChooser()
              }
            }
            Text {
              textFormat: Text.PlainText
              text: "DOWNLOAD"
              color: accentText
              font.family: uiFont
              font.pixelSize: 10
              font.bold: true
              anchors.centerIn: parent
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: db.confirmChooser()
            }
          }
        }
        Text {
          textFormat: Text.PlainText
          text: "Defaults come from Settings. Tier, audio, lyrics and art apply to this click only. SET AS DEFAULTS saves them."
          color: textDim
          font.pixelSize: 9
          wrapMode: Text.WordWrap
          width: 296
        }
      }
      enter: Transition {
        ParallelAnimation {
          NumberAnimation {
            property: "opacity"
            from: 0
            to: 1
            duration: host.hoverMotion ? 120 : 0
          }
          NumberAnimation {
            property: "scale"
            from: 0.8
            to: 1
            duration: host.hoverMotion ? 260 : 0
            easing.type: Easing.OutBack
          }
        }
      }
      exit: Transition {
        ParallelAnimation {
          NumberAnimation {
            property: "opacity"
            from: 1
            to: 0
            duration: host.hoverMotion ? 110 : 0
          }
          NumberAnimation {
            property: "scale"
            from: 1
            to: 0.9
            duration: host.hoverMotion ? 110 : 0
            easing.type: Easing.InQuad
          }
        }
      }
    }
  }
  // Always enabled: a HoverHandler whose enabled flips false UNDER the
  // pointer can latch hovered true (and its cursor claim) until the
  // pointer re-enters, so the state gating lives where the value is
  // consumed instead. Idle, plus the library claim, is what swells:
  // running/queued and a real DOWNLOADED are not clickable, and failed
  // keeps its red frame instead of a green breath.
  HoverHandler {
    id: dbHover
  }
  HoverSwell {
    anchors.fill: parent
    // The claim's swell is GOLD like its label and check: the green
    // breath is the download-action language, and this button is
    // currently declining to be one.
    tone: db.libGuess ? gold : db.libPartialClaim ? cyan : accent
    on: dbHover.hovered && (db.st === "" || db.libClaim)
  }
}

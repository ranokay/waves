import QtQuick
import QtQuick.Effects
import "primitives" as Primitives

// Compact outlined terminal download icon (rows). Shows ↓ / mono % / ✓ / ↺
// with a thin bottom progress line while running.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.dlPct / host.dlSt / host.ledPulse / host.marchTick /
//   host.openLibraryClaim / host.ownBatchHits / host.ownKeys /
//   host.shimmerPhase
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: di
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color bg: "#0d0f12"
  readonly property real btnBorderW: 1.5
  readonly property int btnRad: 8              // button corner radius
  readonly property color cyan: "#56c8d8"   // HIGH tier + queued
  readonly property color cyanCont: "#07232b"   // healthy-lossy pill container
  readonly property color cyanDim: "#3a8d99"
  readonly property color gold: "#ffb01f"   // HI-RES / VIDEO tier + meter mid band
  readonly property color goldCont: "#2a2008"
  readonly property color goldDim: "#b07d18"
  readonly property color green: "#3ef08a"   // LOSSLESS tier + done state
  readonly property color greenCont: "#08230f"
  readonly property color greenDim: "#2aa862"
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color redCont: "#2a0e0c"
  readonly property color textHi: "#e6e8ec"

  // Named so the scenario test can find the compact download control in
  // a track row without matching on the properties it shares with the
  // full button.
  objectName: "downIcon"
  property var onTap: (function () {})
  property string mediaId: ""
  // Opt-in: mediaId is an album/playlist/mix id, not a track id, so it
  // must be resolved through the locally learned collection membership
  // instead of being looked up as if it were a track (see DownloadButton
  // for the same distinction, and why this can never require a fetch).
  property bool collectionCheck: false
  // A copy from an earlier session, straight from the ownership store
  // (checked against the disk, so a deleted file reads as not owned).
  // Live job state always wins; this only fills the idle state.
  property bool owned: false
  // Owned AND current for today's quality setting: an owned copy below the
  // target quality shows Download again (clicking upgrades in place).
  property var _ownIds: null
  // Batch keys for the ids this indicator answers for (host.ownKeys).
  property var _ownKeys: null
  function refreshOwned() {
    if (collectionCheck) {
      // One bridge call for ids + verdict (see collectionOwnership).
      var co = di.mediaId !== "" ? waves.collectionOwnership(di.mediaId) : null
      var ids = co ? co.ids : null
      _ownIds = ids
      _ownKeys = host.ownKeys(ids)
      owned = !!co && co.verdict === "owned"
      return
    }
    _ownKeys = di.mediaId !== "" ? ["," + di.mediaId + ","] : null
    var o = di.mediaId !== "" ? waves.ownershipOf(di.mediaId) : ({})
    owned = o.owned === true && o.up_to_date === true
  }
  // The library twin of `owned`, the same shape (and the same wording,
  // colours and click-through) DownloadButton carries. This icon is the
  // download control of the expanded album and playlist panels, and it
  // was the one download control in the app that never asked the scan:
  // a song already on disk read a plain arrow here while the badge on
  // the row above it said the opposite.
  //
  // ONE object per grain, never four properties: see DownloadButton's
  // libAlbum for the call budget that shape exists to keep.
  property var libAlbum: null
  // The track twin ({artist, title, album, year}), for the rows that
  // download ONE song. Never set for a video: the scan only holds audio.
  property var libTrack: null
  // Kept as a derived read for the Connections guard below: a row that
  // names nothing must not run a handler per committed batch of a
  // running scan.
  readonly property string libTitle: {
    if (libAlbum && libAlbum.title)
      return "" + libAlbum.title
    if (libTrack && libTrack.title)
      return "" + libTrack.title
    return ""
  }
  property bool libPresent: false
  property bool libPartial: false
  property bool libSure: false
  // The matched local folder, carried so the click-through can name it.
  property string libPath: ""
  property bool _libResolved: false
  function refreshLibPresent() {
    _libResolved = true
    var a = di.libAlbum
    if (!a || !a.title) {
      var t = di.libTrack
      if (!t || !t.title) {
        libPresent = false
        libPartial = false
        libSure = false
        libPath = ""
        return
      }
      var tp = waves.libraryTrackPresence("" + (t.artist || ""), "" + t.title, "" + (t.album || ""), "" + (t.year || ""), t.duration_sec || 0, t.explicit === true ? 1 : (t.explicit === false ? 0 : -1));
      // A track has no coverage axis: presence alone is the done
      // shape, and identity alone picks green from gold.
      libPresent = !!(tp && tp.present === true)
      libPartial = false
      libSure = !!(tp && tp.sure === true)
      libPath = libPresent ? ("" + (tp.local_album_id || "")) : ""
      return
    }
    var p = waves.libraryAlbumPresence("" + (a.artist || ""), "" + a.title, "" + (a.year || ""), a.tracks || 0, a.duration_sec || 0, a.explicit === true ? 1 : -1)
    libPresent = !!(p && p.present === true && p.full === true)
    libPartial = !!(p && p.present === true && p.full !== true)
    libSure = !!(p && p.sure === true)
    libPath = libPresent ? ("" + (p.local_album_id || "")) : ""
  }
  // A tag match, not a record of a download Waves made: it wears the
  // done face but keeps a way through, exactly as on the full button.
  readonly property bool libClaim: liveSt === "" && !owned && libPresent
  // The gold face: only the UNPROVEN matches. A sure one falls through
  // to the green done styling (state is the colour) while libClaim keeps
  // routing its click to the gate.
  readonly property bool libGuess: libClaim && !libSure
  // Cyan, and still a live download: completing an album is not a
  // duplicate. Only reachable from libAlbum (a track is never partial).
  readonly property bool libPartialClaim: liveSt === "" && !owned && libPartial
  function openLibraryClaim() {
    host.openLibraryClaim(di.mediaId, di.libTitle, di.libPath, di.libAlbum ? "album" : "track")
  }
  // Only if the libTrack/libAlbum binding has not already answered: an
  // unconditional resolve here is a second call per row.
  Component.onCompleted: {
    refreshOwned()
    if (!_libResolved)
      refreshLibPresent()
  }
  onMediaIdChanged: refreshOwned()
  onCollectionCheckChanged: refreshOwned()
  onLibAlbumChanged: refreshLibPresent()
  onLibTrackChanged: refreshLibPresent()
  Connections {
    target: waves
    enabled: di.libTitle !== ""
    function onLibraryPresenceChanged() {
      di.refreshLibPresent()
    }
  }
  Connections {
    target: waves
    // Empty id = broadcast (the quality setting changed).
    function onOwnershipChanged(tid) {
      if (di.collectionCheck) {
        if (tid === "" || (di._ownIds && di._ownIds.indexOf(tid) !== -1))
          di.refreshOwned()
      } else if (tid === di.mediaId || tid === "") {
        di.refreshOwned()
      }
    }
    function onOwnershipChangedBatch(batch) {
      if (host.ownBatchHits(batch, di._ownKeys))
        di.refreshOwned()
    }
    function onCollectionMembershipChanged(cid) {
      if (di.collectionCheck && cid === di.mediaId)
        di.refreshOwned()
    }
  }
  readonly property string liveSt: di.mediaId !== "" ? host.dlSt(di.mediaId) : ""
  readonly property string st: liveSt !== "" ? liveSt : ((owned || libPresent) ? "done" : "")
  readonly property real pct: di.mediaId !== "" ? host.dlPct(di.mediaId) : -1
  implicitWidth: 32
  implicitHeight: 30
  radius: btnRad
  clip: true
  color: libGuess ? goldCont : libPartialClaim ? cyanCont : st === "done" ? greenCont : st === "failed" ? redCont : accentCont
  border.width: btnBorderW
  border.color: libGuess ? goldDim : libPartialClaim ? cyanDim : st === "failed" ? red : st === "done" ? greenDim : accentDim
  scale: 1
  Behavior on scale {
    NumberAnimation {
      duration: 130
      easing.type: Easing.OutBack
    }
  }
  // RUNNING: an LED matrix backdrop fills the button edge to edge (cells
  // stretch fractionally so there is no leftover padding on any side),
  // filling column by column from the bottom left like the album bar;
  // the % reads on top. Done converts to the usual ✓ chip.
  Item {
    id: diGrid
    visible: di.st === "running"
    anchors.fill: parent
    anchors.margins: btnBorderW   // sit inside the border
    readonly property int gcols: 7
    readonly property int grows: 6
    readonly property real ggap: 1.5
    readonly property real cellW: (width - (gcols - 1) * ggap) / gcols
    readonly property real cellH: (height - (grows - 1) * ggap) / grows
    readonly property int total: gcols * grows
    readonly property int lit: Math.round(Math.max(0, Math.min(100, di.pct)) / 100 * total)
    opacity: 0.5
    // Item clip is square; mask the grid to the button's rounded shape
    // so edge-to-edge cells never poke past the corners.
    layer.enabled: true
    layer.effect: MultiEffect {
      maskEnabled: true
      maskSource: ShaderEffectSource {
        sourceItem: diGridMask
        hideSource: false
      }
    }
    Repeater {
      model: diGrid.total
      delegate: Rectangle {
        required property int index
        readonly property int col: index % diGrid.gcols
        readonly property int rowTop: Math.floor(index / diGrid.gcols)
        // column-major, bottom-up, mirroring DotMatrix's rising fill
        readonly property int fillIndex: col * diGrid.grows + (diGrid.grows - 1 - rowTop)
        readonly property bool litCell: fillIndex < diGrid.lit
        readonly property bool pulsing: fillIndex === diGrid.lit && diGrid.lit < diGrid.total
        // Same finishing twinkle as DotMatrix (this grid is the
        // same visual language, just inlined for the mask effect).
        readonly property real twinkleR: {
          var r = Math.sin(index * 12.9898) * 43758.5453
          return r - Math.floor(r)
        }
        x: col * (diGrid.cellW + diGrid.ggap)
        y: rowTop * (diGrid.cellH + diGrid.ggap)
        width: diGrid.cellW
        height: diGrid.cellH
        radius: 0   // sharp LED cells
        color: accent
        // Breathe off the shared 20 Hz clock (host.ledPulse) rather than
        // a per-frame animation: this grid also runs a layer + mask
        // effect, so a per-frame pulse re-rendered the masked layer every
        // vsync for the whole download. See host.ledPulse.
        opacity: (di.pct >= 99.9 && litCell) ? 0.62 + 0.38 * (0.5 + 0.5 * Math.cos(2 * Math.PI * (host.shimmerPhase * 2 + twinkleR))) : pulsing ? host.ledPulse : (litCell ? 1.0 : 0.16)
      }
    }
  }
  Item {
    id: diGridMask
    anchors.fill: parent
    anchors.margins: btnBorderW
    // NEVER visible: this white rounded rectangle is the SHAPE the
    // MultiEffect masks the LED grid with, and a ShaderEffectSource
    // reads it whether or not the scene draws it. Drawn, it fills the
    // whole button white behind the arrow.
    visible: false
    Rectangle {
      anchors.fill: parent
      radius: btnRad - btnBorderW
      color: "#ffffff"
    }
  }
  Text {
    textFormat: Text.PlainText
    anchors.centerIn: parent
    visible: di.st === "running"
    text: di.pct >= 0 ? Math.round(di.pct) + "%" : "…"
    color: textHi
    font.family: mono
    font.pixelSize: 9
    font.bold: true
    style: Text.Outline
    styleColor: bg
  }
  // "preparing" (parked behind a re-fetch or a folder-tree warm) reads as
  // queued here too: see DownloadButton.waiting.
  readonly property bool waiting: di.st === "queued" || di.st === "preparing"
  Ico {
    anchors.centerIn: parent
    visible: di.st !== "running" && di.st !== "failed" && !di.waiting
    name: di.st === "done" ? "check" : "arrow-down"
    color: di.libGuess ? gold : di.libPartialClaim ? cyan : di.st === "done" ? green : accent
    size: 15
    bold: di.st === "done" ? 0 : 10
  }
  // Queued: click acknowledged, waiting for a download slot; the stack
  // glyph, your item is the bottom bar.
  QueueStack {
    marchTick: host.marchTick
    visible: di.waiting
    barW: 13
    anchors.centerIn: parent
  }
  RetryMark {
    anchors.centerIn: parent
    visible: di.st === "failed"
    color: red
    box: 15
  }
  MouseArea {
    // Named so the scenario test can drive the REAL tap area rather
    // than the function behind it (the wiring is the thing at risk).
    objectName: "diTapArea"
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onPressed: di.scale = 0.85
    onReleased: di.scale = 1.0
    onCanceled: di.scale = 1.0
    // A library claim is a guess, so it answers instead of ignoring:
    // the same conversation the full button opens, with DOWNLOAD
    // ANYWAY one click away.
    onClicked: {
      if (di.libClaim) {
        di.openLibraryClaim()
        return
      }
      if (di.st === "running" || di.st === "done" || di.waiting)
        return
      di.onTap()
    }
  }
}

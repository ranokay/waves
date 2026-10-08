import QtQuick
import QtQuick.Layouts
import "../../primitives" as Primitives
import "../../components"
import "../../primitives"
import "../catalog"
import "../downloads"
import "../providers"

// The unified search results page: one section per media kind over the
// folded rows of every provider that answered.
//
// High-confidence equivalents across providers already fold into one row
// (the bridge's ``sections`` carry each row's ``sources``); nothing here
// names a provider or branches on one -- a row's source marks come from the
// payload, the per-section SHOW ALL persists under neutral pref keys, and a
// third SEARCH provider lands with no edit to this file.
// `host` is Main.qml's root object, bound at the single instantiation and
// required so a missed binding fails at load. It reads through it:
//   host.fill / host.fillMedia / host.filterType / host.height / host.width /
//   host.lastSearchQuery / host.reconcileById / host.searchSections /
//   host.searchOrdered / host.searchRefreshMode / host.searchReveal /
//   host.searchRowVisible / host.sectionVisible / host.rowSourcesById /
//   host.sourceMarksOn / host.submitSearch
// and writes host.filterType through setFilter (the type chip's route, so
// the row windows are re-planned around the change).
// `resultsPane` is the search results Flickable the artist strip's wheel
// redirect drives.
// The palette values are local copies of Main.qml's static literals, except accent and textDim which bind to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Column {
  id: resultsView
  required property var host
  required property Flickable resultsPane
  // The folded payload: kind -> rows (each row carries its own ``sources``
  // in the bridge payload; host lifts them into rowSourcesById so a QML
  // ListModel never holds a nested list).
  property var sections: ({})
  // The first provider's pinned best match, or null.
  property var topRow: null
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent and textDim bind to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color gold: "#ffb01f"   // HI-RES / VIDEO tier + meter mid band
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color textDim: Primitives.Palette.textDim
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"
  // Set once the declared children exist: the data handler must not run
  // mid-construction, when the models are not there yet.
  property bool ready: false
  // Neutral section prefs: one SHOW ALL state per kind, carried over from
  // the per-provider keys on first load (see the bridge's prefs migration).
  property var expanded: ({})
  // A section a user expanded once keeps its rows BUILT through SHOW LESS
  // and its chips until the next search: the rows become hidden, not
  // destroyed, so a second SHOW ALL costs nothing. Seeded from the
  // pref-backed expansion state on each page (a section left expanded keeps
  // the same guarantee).
  property var kept: ({})
  // The list rows' reserved heights (their components' own heights), shared
  // with the plan's pitch arithmetic so a row-height change is one edit.
  readonly property var _listRowH: ({
      albums: 64,
      tracks: 62,
      playlists: 64,
      mixes: 66
    })
  // The sortable rows, held raw (not the lossy model copies) so every
  // field, the full date included, survives a re-sort.
  property var albumsRaw: []
  property var tracksRaw: []
  property var videosRaw: []
  width: parent ? parent.width : 0
  spacing: 8

  // One model set for the whole page: each list holds the folded rows of
  // its kind, whichever providers they came from.
  ListModel {
    id: artistsModel
  }
  ListModel {
    id: albumsModel
  }
  ListModel {
    id: tracksModel
  }
  ListModel {
    id: videosModel
  }
  ListModel {
    id: playlistsModel
  }
  ListModel {
    id: mixesModel
  }
  // The pinned row's section gate (the header and the row read it), and
  // read handles for the scenarios that compare layout or delegate
  // identity across a refresh.
  readonly property bool topVisible: host.filterType === "all" && resultsView.topRow !== null && host.rowMatchesSource(resultsView.topRow)
  property alias topHeadItem: topHead
  property alias topRepeater: topRep
  property alias artistsHeadItem: artistsHead
  property alias albumRepeater: albumsRep
  property alias tracksRepeater: tracksRep
  property alias videoGridItem: videoGrid
  property alias artistsFlowItem: artistFlow

  function modelFor(name) {
    return name === "artists" ? artistsModel : name === "albums" ? albumsModel : name === "tracks" ? tracksModel : name === "videos" ? videosModel : name === "playlists" ? playlistsModel : name === "mixes" ? mixesModel : null
  }
  function countFor(name) {
    var m = resultsView.modelFor(name)
    return m ? m.count : 0
  }
  readonly property int rowCount: resultsView.countFor("artists") + resultsView.countFor("albums") + resultsView.countFor("tracks") + resultsView.countFor("videos") + resultsView.countFor("playlists") + resultsView.countFor("mixes")
  // A section a provider answered is present in the payload; one no arrived
  // provider answers is absent and shows nothing.
  function isExpanded(name) {
    return resultsView.expanded[name] === true
  }
  function keptFor(name) {
    return resultsView.kept[name] === true
  }
  function markKept(name) {
    var keep = {}
    for (var k in resultsView.kept)
      keep[k] = resultsView.kept[k]
    keep[name] = true
    resultsView.kept = keep
  }
  // A fresh page seeds the kept flags from the pref-backed expansion state,
  // so a section the user left expanded keeps its rows, while a flag left
  // from the last search (SHOW ALL then SHOW LESS) cannot build every row
  // past this page's caps.
  function seedKept() {
    var keep = {}
    for (var k in resultsView.expanded)
      keep[k] = resultsView.expanded[k]
    resultsView.kept = keep
  }
  function toggleExpanded(name) {
    // SHOW ALL builds the screen it reveals in this click, so the frame the
    // rows appear on is finished; the rest incubate below. SHOW LESS keeps
    // them built, hidden (the kept flags, set here before the reveal). The
    // windows close first: a still-incubating row must not be forced to
    // finish inline by a window opened over the old page.
    resultsView.closeWindows()
    var next = {}
    for (var key in resultsView.expanded)
      next[key] = resultsView.expanded[key]
    next[name] = !resultsView.isExpanded(name)
    if (next[name])
      resultsView.markKept(name)
    resultsView.expanded = next
    waves.setWavesPref("search_section_" + name + "_expanded", next[name])
    resultsView.planSync(resultsPane.contentY, name)
  }
  function readPrefs() {
    var next = ({})
    var names = ["artists", "albums", "tracks", "videos", "playlists", "mixes"]
    for (var i = 0; i < names.length; ++i)
      next[names[i]] = waves.wavesPref("search_section_" + names[i] + "_expanded") === true
    resultsView.expanded = next
    resultsView.seedKept()
  }
  // A section shows while the active chips can host its rows (the shared
  // filter rule); the source chip narrows the count the rule reads, so a
  // section no matching source answers leaves the page with its rows.
  function filteredCountFor(name) {
    var rows = resultsView.sections[name] || []
    var total = 0
    for (var i = 0; i < rows.length; ++i)
      if (host.rowMatchesSource(rows[i]))
        total += 1
    return total
  }
  function sectionVisible(name) {
    return host.sectionVisible(name, resultsView.filteredCountFor(name))
  }
  // A delegate's own gate: the row must belong to the page's shape
  // (host.searchRowVisible) and to the active source chip.
  function rowVisible(name, index) {
    return host.searchRowVisible(name, resultsView.countFor(name), index, resultsView.isExpanded(name)) && host.rowMatchesSourceById(resultsView.modelIdFor(name, index))
  }
  function rowVisibleCapped(name, index, cap) {
    return host.searchRowVisible(name, resultsView.countFor(name), index, resultsView.isExpanded(name), cap) && host.rowMatchesSourceById(resultsView.modelIdFor(name, index))
  }
  function modelIdFor(name, index) {
    var m = resultsView.modelFor(name)
    return m && index < m.count ? m.get(index).id : ""
  }
  // --- Row windows --------------------------------------------------------
  // [from, to) per section: the rows the handler turn builds INLINE, so the
  // frame the page lands on is the finished screen. Every other shown row
  // incubates asynchronously with its height reserved (the delegates'
  // height bindings), so nothing on screen moves when it lands and the page
  // fills in from the fold down. The window is planned from the Column's
  // own layout arithmetic, not the live delegates: at plan time the new
  // rows have not been positioned (or created) yet. Everything that makes
  // rows appear (a fresh search, SHOW ALL or LESS, a chip, the sort
  // control) closes the windows, makes its change, and only then plans and
  // opens the new ones: a row whose `asynchronous` turns false finishes its
  // incubation on the spot, and opening a window while old rows still stood
  // would force any of them still incubating to finish on their way out.
  property var winFrom: ({})
  property var winTo: ({})
  function inWindow(name, index) {
    return index >= 0 && index >= (resultsView.winFrom[name] || 0) && index < (resultsView.winTo[name] || 0)
  }
  function closeWindows() {
    resultsView.winFrom = ({})
    resultsView.winTo = ({})
  }
  // The plan measures the results Column at the page's own geometry: a
  // spacing-8 Column of 36px headers, 16px SHOW ALL lines and the rows'
  // reserved heights. `atY` is where the pane lands after the change
  // (results.contentY; 0 for a fresh search — a Back armed on the pane is
  // not part of this page). `fromSection` (a section whose own SHOW ALL /
  // SHOW LESS was clicked) keeps its header in view in the window: SHOW
  // LESS scrolls back up to it, and the rows there must be built for that
  // frame.
  function planSync(atY, fromSection) {
    var host = resultsView.host
    var all = host.filterType === "all"
    var w = resultsView.width > 0 ? resultsView.width : (host.width > 0 ? host.width : 1100)
    var screen = host.height > 0 ? host.height : 900
    var y = 8
    var headY = ({})
    var secs = ({})
    function block(h) {
      y += h + 8
    }
    // A 5-capped list row section's own shape: header, shown rows, SHOW ALL.
    function list(name, n, h, cap, expanded) {
      if (!resultsView.sectionVisible(name))
        return
      headY[name] = y
      block(36)
      var shown = all ? (expanded ? n : Math.min(n, cap)) : n
      secs[name] = {
        y: y,
        shown: shown,
        pitch: h + 8,
        per: 1
      }
      if (shown > 0)
        block(shown * (h + 8) - 8)
      if (all && n > cap)
        block(16)
    }
    if (all && resultsView.topVisible) {
      block(36)
      var kind = resultsView.topRow.kind
      block(kind === "album" || kind === "playlist" ? 64 : 62)
    }
    var na = artistsModel.count
    if (resultsView.sectionVisible("artists")) {
      headY.artists = y
      block(36)
      var gc = Math.max(1, Math.floor((w + 12) / (190 + 12)))
      var cardW = (w - (gc - 1) * 12) / gc
      var rowH = cardW + 142
      var shownA = all ? (resultsView.isExpanded("artists") ? na : Math.min(na, 5)) : na
      secs.artists = {
        y: y,
        shown: shownA,
        pitch: rowH + 12,
        per: gc
      }
      if (shownA > 0)
        block(Math.ceil(shownA / gc) * (rowH + 12) - 12)
      if (all && na > 5)
        block(16)
    }
    list("albums", albumsModel.count, resultsView._listRowH.albums, 5, resultsView.isExpanded("albums"))
    list("tracks", tracksModel.count, resultsView._listRowH.tracks, 5, resultsView.isExpanded("tracks"))
    var nv = videosModel.count
    if (resultsView.sectionVisible("videos")) {
      headY.videos = y
      block(36)
      var vc = Math.max(2, Math.floor(w / 320))
      var cellW = (w - (vc - 1) * 18) / vc
      var cellH = Math.round(cellW * 9 / 16) + 54
      var vcap = vc * Math.ceil(5 / vc)
      var shownV = all ? (resultsView.isExpanded("videos") ? nv : Math.min(nv, vcap)) : nv
      secs.videos = {
        y: y,
        shown: shownV,
        pitch: cellH + 18,
        per: vc
      }
      if (shownV > 0)
        block(Math.ceil(shownV / vc) * (cellH + 18) - 18)
      if (all && nv > vcap)
        block(16)
    }
    list("playlists", playlistsModel.count, resultsView._listRowH.playlists, 5, resultsView.isExpanded("playlists"))
    list("mixes", mixesModel.count, resultsView._listRowH.mixes, 5, resultsView.isExpanded("mixes"))
    var contentH = y + 8
    var land = Math.max(0, Math.min(atY || 0, contentH - screen))
    var top = fromSection !== undefined && headY[fromSection] !== undefined ? Math.min(land, headY[fromSection]) : land
    var bottom = land + screen + 64
    var from = ({})
    var to = ({})
    var names = ["artists", "albums", "tracks", "videos", "playlists", "mixes"]
    for (var i = 0; i < names.length; ++i) {
      var name = names[i]
      var s = secs[name]
      if (!s || s.shown <= 0) {
        from[name] = 0
        to[name] = 0
        continue
      }
      var lines = Math.ceil(s.shown / s.per)
      var a = Math.max(0, Math.min(lines, Math.floor((top - s.y) / s.pitch)))
      var b = Math.max(0, Math.min(lines, Math.ceil((bottom - s.y) / s.pitch)))
      from[name] = a * s.per
      to[name] = Math.min(s.shown, b * s.per)
    }
    resultsView.winFrom = from
    resultsView.winTo = to
  }
  // A type chip: a whole section's rows show, so it builds them the way
  // SHOW ALL does, and keeps them (the chip back to All frees nothing).
  // The screen the page lands on is built in the click.
  function setFilter(name) {
    if (name === host.filterType)
      return
    resultsView.closeWindows()
    if (name !== "all")
      resultsView.markKept(name)
    host.filterType = name
    resultsView.planSync(resultsPane.contentY, name)
  }
  // A row's source marks, gated by the page: a single-source install has
  // nothing to disambiguate and draws no marks; with two or more sources
  // every row names its own. A row outside the lifted side map (the pinned
  // top, when the provider's pin is not also one of its list rows) reads its
  // own sources from the payload.
  function rowSources(id) {
    if (!host.sourceMarksOn)
      return []
    var known = host.rowSourcesById[id]
    if (known !== undefined)
      return known
    if (resultsView.topRow !== null && String(resultsView.topRow.id) === String(id))
      return resultsView.topRow.sources || []
    return []
  }
  function apply(inPlace) {
    var inPlaceSwap = inPlace === true
    resultsView.albumsRaw = resultsView.sections.albums || []
    resultsView.tracksRaw = resultsView.sections.tracks || []
    resultsView.videosRaw = resultsView.sections.videos || []
    if (inPlaceSwap) {
      // A refresh swaps the rows under a page the user is already reading:
      // delegates are kept and reconciled by id, so nothing flickers,
      // scrolls or loses focus.
      host.reconcileById(artistsModel, resultsView.sections.artists || [], false)
      host.reconcileById(albumsModel, host.searchOrdered(resultsView.albumsRaw, true), true)
      host.reconcileById(tracksModel, host.searchOrdered(resultsView.tracksRaw, true), true)
      host.reconcileById(videosModel, host.searchOrdered(resultsView.videosRaw, false), true)
      host.reconcileById(playlistsModel, resultsView.sections.playlists || [], false)
      host.reconcileById(mixesModel, resultsView.sections.mixes || [], false)
      // Rows the refresh added inside the kept windows build inline; the
      // re-plan keeps the windows true to the new counts.
      resultsView.planSync(resultsPane.contentY)
    } else {
      // A fresh search: close the windows over the OLD rows (a dying
      // delegate reads index -1 and must incubate, not finish inline),
      // rebuild, then plan the screen the page opens on. The kept flags
      // reset to the expansion state this page starts with.
      resultsView.closeWindows()
      resultsView.seedKept()
      host.fill(artistsModel, resultsView.sections.artists || [])
      host.fillMedia(albumsModel, host.searchOrdered(resultsView.albumsRaw, true))
      host.fillMedia(tracksModel, host.searchOrdered(resultsView.tracksRaw, true))
      host.fillMedia(videosModel, host.searchOrdered(resultsView.videosRaw, false))
      host.fill(playlistsModel, resultsView.sections.playlists || [])
      host.fill(mixesModel, resultsView.sections.mixes || [])
      resultsView.planSync(0)
    }
  }
  function applySort(inPlace) {
    // inPlace: a refresh swapping rows under a page the user is already
    // reading, where a clear+rebuild would freeze the window (see
    // host.reconcileById). Every other caller, a fresh search and the
    // sort control alike, is a deliberate full rebuild.
    if (inPlace === true) {
      host.reconcileById(albumsModel, host.searchOrdered(resultsView.albumsRaw, true), true)
      host.reconcileById(tracksModel, host.searchOrdered(resultsView.tracksRaw, true), true)
      host.reconcileById(videosModel, host.searchOrdered(resultsView.videosRaw, false), true)
      resultsView.planSync(resultsPane.contentY)
    } else {
      resultsView.closeWindows()
      host.fillMedia(albumsModel, host.searchOrdered(resultsView.albumsRaw, true))
      host.fillMedia(tracksModel, host.searchOrdered(resultsView.tracksRaw, true))
      host.fillMedia(videosModel, host.searchOrdered(resultsView.videosRaw, false))
      resultsView.planSync(resultsPane.contentY)
    }
  }
  function updateArtistPop(id, pop) {
    for (var i = 0; i < artistsModel.count; ++i)
      if (artistsModel.get(i).id === id) {
        artistsModel.setProperty(i, "popularity", pop)
        break
      }
  }

  Component.onCompleted: {
    resultsView.readPrefs()
    resultsView.ready = true
    resultsView.apply(host.searchRefreshMode)
  }
  onSectionsChanged: if (resultsView.ready)
    resultsView.apply(host.searchRefreshMode)

  // TOP RESULT: the first provider's own best match, pinned above every
  // section of the mixed All view (a provider that answers none pins
  // nothing). The item still sits in its section below: this is a pointer,
  // not a move.
  SectionHeader {
    id: topHead
    opacity: host.searchReveal
    visible: resultsView.topVisible
    label: "TOP RESULT"
  }
  Repeater {
    id: topRep
    model: resultsView.topRow !== null ? [resultsView.topRow] : []
    delegate: Loader {
      id: topLd
      required property var modelData
      visible: resultsView.topVisible
      width: parent.width
      opacity: host.searchReveal
      sourceComponent: topLd.modelData.kind === "album" ? topAlbumComp : topLd.modelData.kind === "playlist" ? topPlaylistComp : topTrackComp
      Component {
        id: topAlbumComp
        AlbumBlock {
          host: resultsView.host
          albumId: topLd.modelData.id
          title: topLd.modelData.title
          artistName: topLd.modelData.artist
          artistId: topLd.modelData.artist_id || ""
          art: topLd.modelData.art
          year: "" + (topLd.modelData.year || "")
          releaseDate: topLd.modelData.date || ""
          listedDate: topLd.modelData.listed || ""
          trackCount: topLd.modelData.tracks || 0
          durationSec: topLd.modelData.duration_sec || 0
          quality: topLd.modelData.quality || ""
          popularity: topLd.modelData.popularity || 0
          sources: resultsView.rowSources(topLd.modelData.id)
        }
      }
      Component {
        id: topTrackComp
        TrackRow {
          host: resultsView.host
          tId: topLd.modelData.id
          kind: topLd.modelData.kind
          title: topLd.modelData.title
          artistName: topLd.modelData.artist || ""
          artistId: topLd.modelData.artist_id || ""
          album: topLd.modelData.album || ""
          art: topLd.modelData.art || ""
          year: "" + (topLd.modelData.year || "")
          date: topLd.modelData.date || ""
          duration: topLd.modelData.duration || ""
          durationSec: topLd.modelData.duration_sec || 0
          quality: topLd.modelData.quality || ""
          popularity: topLd.modelData.popularity || 0
          explicit: topLd.modelData.explicit === true
          albumId: topLd.modelData.album_id || ""
          sources: resultsView.rowSources(topLd.modelData.id)
        }
      }
      Component {
        id: topPlaylistComp
        PlaylistBlock {
          host: resultsView.host
          plId: topLd.modelData.id
          title: topLd.modelData.title
          creator: topLd.modelData.creator || ""
          art: topLd.modelData.art
          trackCount: topLd.modelData.tracks || 0
          sources: resultsView.rowSources(topLd.modelData.id)
        }
      }
    }
  }

  // ARTISTS. The unified surface draws one flow grid; a row never folds
  // across providers (names are not automatic identity), so each card
  // names its own source.
  SectionHeader {
    id: artistsHead
    opacity: host.searchReveal
    visible: resultsView.sectionVisible("artists")
    label: "ARTISTS"
    count: artistsModel.count
  }
  Flow {
    id: artistFlow
    visible: resultsView.sectionVisible("artists")
    width: parent.width
    spacing: 12
    property int cols: Math.max(1, Math.floor((width + spacing) / (190 + spacing)))
    property real cardW: (width - (cols - 1) * spacing) / cols
    Repeater {
      model: artistsModel
      delegate: Loader {
        // Past the cap a card stays an empty Loader until SHOW ALL (or the
        // Artists chip) makes it shown; once built it stays built, hidden,
        // through SHOW LESS until the next search. `index >= 0` guards the
        // dying delegate a model removal reads -1 on its way out: it must
        // read as NOT shown, or the page builds every unbuilt row inline
        // while the old page is clearing.
        readonly property bool shown: index >= 0 && resultsView.rowVisible("artists", index)
        active: shown || (index >= 0 && (index < 5 || resultsView.keptFor("artists")))
        visible: shown
        width: artistFlow.cardW
        height: item ? item.implicitHeight : width + 142
        asynchronous: !shown || !resultsView.inWindow("artists", index)
        opacity: host.searchReveal
        sourceComponent: ArtistSearchCard {
          host: resultsView.host
          aArt: model.art
          aName: model.name
          aPop: model.popularity
          aId: model.id
          sources: resultsView.rowSources(model.id)
        }
      }
    }
  }
  ShowAllLabel {
    host: resultsView.host
    objectName: "artistsShowAll"
    opacity: host.searchReveal
    sectionTop: artistsHead
    // Offer SHOW ALL only when there is more to reveal: the flow's
    // five-row cap. The count gate is what the sections get from
    // sectionVisible(); without it the expanded flag (pref-backed) would
    // keep this label on screen over an empty page.
    visible: resultsView.sectionVisible("artists") && host.filterType === "all" && artistsModel.count > 0 && (resultsView.isExpanded("artists") || artistsModel.count > 5)
    expanded: resultsView.isExpanded("artists")
    count: artistsModel.count
    onToggled: resultsView.toggleExpanded("artists")
  }

  // ALBUMS
  SectionHeader {
    id: albumsHead
    opacity: host.searchReveal
    visible: resultsView.sectionVisible("albums")
    label: "ALBUMS"
    count: albumsModel.count
  }
  Repeater {
    id: albumsRep
    model: albumsModel
    delegate: Loader {
      // The section filter must hide the LOADER (the Column child);
      // an invisible item inside a sized Loader would still occupy
      // its row. In the mixed All view only the first 5 show until
      // SHOW ALL; a row past the cap is not built until then, and once
      // built it stays built (hidden) through SHOW LESS. `index >= 0`
      // guards the dying delegate a model removal reads -1 on: it must
      // read as NOT shown, or the clearing page builds every unbuilt
      // row inline.
      readonly property bool shown: index >= 0 && resultsView.rowVisible("albums", index)
      active: shown || (index >= 0 && (index < 5 || resultsView.keptFor("albums")))
      visible: shown
      width: parent.width
      height: item ? item.implicitHeight : resultsView._listRowH.albums
      asynchronous: !shown || !resultsView.inWindow("albums", index)
      opacity: host.searchReveal
      sourceComponent: AlbumBlock {
        host: resultsView.host
        albumId: model.id
        title: model.title
        artistName: model.artist
        artistId: model.artist_id
        art: model.art
        year: model.year
        releaseDate: model.date
        listedDate: model.listed || ""
        trackCount: model.tracks
        durationSec: model.duration_sec || 0
        quality: model.quality
        popularity: model.popularity
        sources: resultsView.rowSources(model.id)
      }
    }
  }
  SearchSectionMore {
    host: resultsView.host
    section: "albums"
    sectionTop: albumsHead
    count: albumsModel.count
    expanded: resultsView.isExpanded("albums")
    group: resultsView
  }

  // TRACKS
  SectionHeader {
    id: tracksHead
    opacity: host.searchReveal
    visible: resultsView.sectionVisible("tracks")
    label: "TRACKS"
    count: tracksModel.count
  }
  Repeater {
    id: tracksRep
    model: tracksModel
    delegate: Loader {
      readonly property bool shown: index >= 0 && resultsView.rowVisible("tracks", index)
      active: shown || (index >= 0 && (index < 5 || resultsView.keptFor("tracks")))
      visible: shown
      width: parent.width
      height: resultsView._listRowH.tracks   // TrackRow's fixed height
      asynchronous: !shown || !resultsView.inWindow("tracks", index)
      opacity: host.searchReveal
      sourceComponent: TrackRow {
        host: resultsView.host
        tId: model.id
        title: model.title
        artistName: model.artist
        artistId: model.artist_id
        album: model.album
        art: model.art
        year: model.year
        date: model.date
        duration: model.duration
        durationSec: model.duration_sec || 0
        quality: model.quality
        popularity: model.popularity
        explicit: model.explicit === true
        albumId: model.album_id || ""
        sources: resultsView.rowSources(model.id)
      }
    }
  }
  SearchSectionMore {
    host: resultsView.host
    section: "tracks"
    sectionTop: tracksHead
    count: tracksModel.count
    expanded: resultsView.isExpanded("tracks")
    group: resultsView
  }

  // VIDEOS: art-first results, 16:9 thumbnails at grid size, with the
  // title, artist, release date and a full download button reading
  // underneath. Cells are sized from the section width, so the column
  // count follows the window.
  SectionHeader {
    id: videosHead
    opacity: host.searchReveal
    visible: resultsView.sectionVisible("videos")
    label: "VIDEOS"
    count: videosModel.count
  }
  Flow {
    id: videoGrid
    width: parent.width
    spacing: 18
    readonly property int cols: Math.max(2, Math.floor(width / 320))
    readonly property real cellW: (width - (cols - 1) * spacing) / cols
    // The mixed view's five, rounded up to whole rows: a grid three
    // wide showed five cells and left the sixth blank, a hole SHOW
    // ALL then filled. Six at three columns, six at two, eight at four.
    readonly property int cap: cols * Math.ceil(5 / cols)
    Repeater {
      model: videosModel
      delegate: Loader {
        readonly property bool shown: index >= 0 && resultsView.rowVisibleCapped("videos", index, videoGrid.cap)
        active: shown || (index >= 0 && (index < videoGrid.cap || resultsView.keptFor("videos")))
        visible: shown
        width: videoGrid.cellW
        height: Math.round(videoGrid.cellW * 9 / 16) + 54
        asynchronous: !shown || !resultsView.inWindow("videos", index)
        opacity: host.searchReveal
        sourceComponent: VideoCell {
          host: resultsView.host
          width: videoGrid.cellW
          vid: model.id
          vcTitle: model.title
          vcArtist: model.artist
          artUrl: model.art
          artBigUrl: model.art_big || ""
          vcDuration: model.duration
          vcExplicit: model.explicit === true
          vcSpec: model.quality || ""
          vcDate: model.date
          sources: resultsView.rowSources(model.id)
        }
      }
    }
  }
  SearchSectionMore {
    host: resultsView.host
    section: "videos"
    sectionTop: videosHead
    count: videosModel.count
    expanded: resultsView.isExpanded("videos")
    group: resultsView
    cap: videoGrid.cap
  }

  // PLAYLISTS
  SectionHeader {
    id: playlistsHead
    opacity: host.searchReveal
    visible: resultsView.sectionVisible("playlists")
    label: "PLAYLISTS"
    count: playlistsModel.count
  }
  Repeater {
    model: playlistsModel
    delegate: Loader {
      readonly property bool shown: index >= 0 && resultsView.rowVisible("playlists", index)
      active: shown || (index >= 0 && (index < 5 || resultsView.keptFor("playlists")))
      visible: shown
      width: parent.width
      asynchronous: !shown || !resultsView.inWindow("playlists", index)
      opacity: host.searchReveal
      // Reserve the row's height while it incubates: without it the
      // section collapses to zero and pops open as each row lands.
      height: item ? item.implicitHeight : resultsView._listRowH.playlists
      sourceComponent: PlaylistBlock {
        host: resultsView.host
        plId: model.id
        title: model.title
        creator: model.creator || ""
        art: model.art
        trackCount: model.tracks
        sources: resultsView.rowSources(model.id)
      }
    }
  }
  SearchSectionMore {
    host: resultsView.host
    section: "playlists"
    sectionTop: playlistsHead
    count: playlistsModel.count
    expanded: resultsView.isExpanded("playlists")
    group: resultsView
  }

  // MIXES
  SectionHeader {
    id: mixesHead
    opacity: host.searchReveal
    visible: resultsView.sectionVisible("mixes")
    label: "MIXES"
    count: mixesModel.count
  }
  Repeater {
    model: mixesModel
    delegate: Loader {
      readonly property bool shown: index >= 0 && resultsView.rowVisible("mixes", index)
      active: shown || (index >= 0 && (index < 5 || resultsView.keptFor("mixes")))
      visible: shown
      width: parent.width
      height: resultsView._listRowH.mixes
      asynchronous: !shown || !resultsView.inWindow("mixes", index)
      opacity: host.searchReveal
      sourceComponent: Rectangle {
        radius: 10
        color: surface
        border.color: border1
        RowLayout {
          anchors.fill: parent
          anchors.margins: 10
          spacing: 13
          Art {
            host: resultsView.host
            width: 46
            height: 46
            hoverFx: true
            fxKind: "mix"
            fxId: "" + (model.id || "")
            url: model.art
          }
          ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Text {
              textFormat: Text.PlainText
              text: model.title
              color: textHi
              font.pixelSize: 15
              font.bold: true
              elide: Text.ElideRight
              Layout.fillWidth: true
            }
            Text {
              textFormat: Text.PlainText
              text: model.subtitle ? model.subtitle : "Mix"
              color: textLo
              font.pixelSize: 12
              elide: Text.ElideRight
              Layout.fillWidth: true
            }
          }
          SourceMarks {
            Layout.alignment: Qt.AlignVCenter
            sources: resultsView.rowSources(model.id)
          }
          DownloadButton {
            host: resultsView.host
            mediaId: model.id
            chooserKind: "mix"
            collectionCheck: true
            label: "Download mix"
            onTap: function () {
              waves.downloadMix(model.id)
            }
          }
        }
      }
    }
  }
  SearchSectionMore {
    host: resultsView.host
    section: "mixes"
    sectionTop: mixesHead
    count: mixesModel.count
    expanded: resultsView.isExpanded("mixes")
    group: resultsView
  }
}

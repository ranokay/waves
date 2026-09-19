import QtQuick
import QtQuick.Layouts

// One provider's group in the search results (issue #292).
//
// The search payload is a list of provider groups; this component renders
// one, and nothing here names a provider: the head's name, mark and sizes
// come from the descriptor the bridge answers for the group's provider id
// (issue #278), the sections render from the group's own rows, the fold
// and the per-section SHOW ALL persist under the provider's own pref keys,
// and the artists layout is the one the payload says the provider ships.
// TIDAL, Apple and any later SEARCH provider all land through this same
// body -- the results page's Repeater is the only caller.
// `host` is Main.qml's root object, bound at the single instantiation
// (the results page's Repeater) and required so a missed binding fails at
// load.
// It reads through it:
//   host._searchBuildTick() / host.fill / host.fillMedia / host.filterType /
//   host.lastSearchQuery / host.reconcileById / host.searchBuilding /
//   host.searchGroups / host.searchOrdered / host.searchRefreshMode /
//   host.searchReveal / host.searchRowVisible / host.sectionVisible /
//   host.submitSearch
// `resultsPane` is the search results Flickable the artist strip's wheel
// redirect drives. `index` is the Repeater's delegate index: the caller's
// `groupData: root.searchGroups[index]` picks this group's payload entry with
// it.
// Split out of Main.qml (#315 slice 6). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Column {
  id: group
  required property var host
  required property Flickable resultsPane
  required property int index
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color gold: "#ffb01f"   // HI-RES / VIDEO tier + meter mid band
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  property var groupData: ({})
  // Set once the declared children exist: the data handler must not run
  // mid-construction, when the models are not there yet.
  property bool ready: false
  readonly property string providerId: String(group.groupData.provider || "")
  readonly property var descriptor: waves.providerDescriptor(group.providerId)
  readonly property string errorText: String(group.groupData.error || "")
  readonly property bool errorStands: group.errorText !== ""
  // "strip" keeps TIDAL's horizontal shelf; every other layout flows.
  readonly property bool stripArtists: String(group.groupData.artists_layout || "") === "strip"
  // A lone group's head stays off when its provider says the page is
  // already its own shape (TIDAL); anything else keeps it.
  readonly property bool headWhenAlone: group.groupData.head_when_alone !== false
  // The provider's pinned best match, a row dict tagged with its kind,
  // or null (TIDAL answers one; a provider that does not leaves null).
  readonly property var topRow: group.groupData.top || null
  // The head's furniture is the provider's own (issue #292): "accent"
  // is TIDAL's shipped head (hover-lit accent name, accent rule, 42px),
  // anything else the neutral 50px head Apple has always shown.
  readonly property bool accentHead: String(group.descriptor ? group.descriptor.head_style : "") === "accent"
  // The fold, and the SHOW ALL state, are per provider: pref-backed so
  // they survive a restart.
  property bool collapsed: false
  property var expanded: ({})
  // This group's sortable rows, held raw (not the lossy model copies) so
  // every field, the full date included, survives a re-sort.
  property var albumsRaw: []
  property var tracksRaw: []
  property var videosRaw: []
  width: parent ? parent.width : 0
  spacing: 8
  // A group with nothing to show (no rows, no pin, no error) takes no
  // room and no Column spacing: the payload carries every enabled
  // provider, and an empty one must not pad the page. The head's own
  // gate is separate (a lone TIDAL group shows rows and no head).
  visible: group.rowCount > 0 || group.topRow !== null || group.errorStands

  // This group's own row models: one set per group instance, so a second
  // provider's rows can never land in the first provider's lists.
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
  readonly property bool topVisible: !group.collapsed && host.filterType === "all" && group.topRow !== null
  property alias topHeadItem: topHead
  property alias topRepeater: topRep
  property alias artistsHeadItem: artistsHead
  property alias albumRepeater: albumsRep
  property alias videoGridItem: videoGrid
  readonly property real stripX: artistStrip.contentX
  function scrollStrip(x) {
    artistStrip.contentX = x
  }

  function modelFor(name) {
    return name === "artists" ? artistsModel : name === "albums" ? albumsModel : name === "tracks" ? tracksModel : name === "videos" ? videosModel : name === "playlists" ? playlistsModel : name === "mixes" ? mixesModel : null
  }
  function countFor(name) {
    var m = group.modelFor(name)
    return m ? m.count : 0
  }
  readonly property int rowCount: group.countFor("artists") + group.countFor("albums") + group.countFor("tracks") + group.countFor("videos") + group.countFor("playlists") + group.countFor("mixes")
  // A bucket the payload omits is one this provider's search never
  // answers, so the active type filter can never host this group's head
  // (issue #241 / UI-05's videos/mixes rule, generic in #292).
  function hostable(name) {
    return group.groupData[name] !== undefined
  }
  function isExpanded(name) {
    return group.expanded[name] === true
  }
  function toggleExpanded(name) {
    var next = {}
    for (var key in group.expanded)
      next[key] = group.expanded[key]
    next[name] = !group.isExpanded(name)
    group.expanded = next
    waves.setWavesPref(group.providerId + "_search_sec_" + name + "_expanded", next[name])
  }
  function readPrefs() {
    group.collapsed = waves.wavesPref("search_provider_" + group.providerId + "_collapsed") === true
    var next = ({})
    var names = ["artists", "albums", "tracks", "videos", "playlists", "mixes"]
    for (var i = 0; i < names.length; ++i)
      next[names[i]] = waves.wavesPref(group.providerId + "_search_sec_" + names[i] + "_expanded") === true
    group.expanded = next
  }
  function toggleCollapsed() {
    group.collapsed = !group.collapsed
    waves.setWavesPref("search_provider_" + group.providerId + "_collapsed", group.collapsed)
  }
  // A section shows while the group is open and the active chip can host
  // its rows (host.sectionVisible is the shared filter rule).
  function sectionVisible(name) {
    return !group.collapsed && host.sectionVisible(name, group.countFor(name))
  }
  // The head only makes sense while the active chip can still show one
  // of this group's rows; a failed fetch has no rows, so its words keep
  // the head wherever its rows could have appeared. A lone group shows
  // no head when its provider says the page is already its own shape
  // (TIDAL-only stays the shipped headless page), but the honest words
  // always keep it (issue #241 / UI-05).
  readonly property bool headVisible: {
    if (group.providerId === "")
      return false
    if (host.filterType !== "all" && !group.hostable(host.filterType))
      return false
    var rows = host.filterType === "all" ? group.rowCount : group.countFor(host.filterType)
    if (rows <= 0 && !group.errorStands)
      return false
    return !(host.searchGroups.length <= 1 && !group.headWhenAlone && !group.errorStands)
  }
  function applyGroup(inPlace) {
    group.albumsRaw = group.groupData.albums || []
    group.tracksRaw = group.groupData.tracks || []
    group.videosRaw = group.groupData.videos || []
    group.applySort(inPlace === true)
  }
  function applySort(inPlace) {
    // inPlace: a refresh swapping rows under a page the user is already
    // reading, where a clear+rebuild would freeze the window (see
    // host.reconcileById). Every other caller, a fresh search and the
    // sort control alike, is a deliberate full rebuild.
    if (inPlace === true) {
      host.reconcileById(artistsModel, group.groupData.artists || [], false)
      host.reconcileById(albumsModel, host.searchOrdered(group.albumsRaw, true), true)
      host.reconcileById(tracksModel, host.searchOrdered(group.tracksRaw, true), true)
      host.reconcileById(videosModel, host.searchOrdered(group.videosRaw, false), true)
      host.reconcileById(playlistsModel, group.groupData.playlists || [], false)
      host.reconcileById(mixesModel, group.groupData.mixes || [], false)
    } else {
      host.fill(artistsModel, group.groupData.artists || [])
      host.fillMedia(albumsModel, host.searchOrdered(group.albumsRaw, true))
      host.fillMedia(tracksModel, host.searchOrdered(group.tracksRaw, true))
      host.fillMedia(videosModel, host.searchOrdered(group.videosRaw, false))
      host.fill(playlistsModel, group.groupData.playlists || [])
      host.fill(mixesModel, group.groupData.mixes || [])
    }
  }
  function updateArtistPop(id, pop) {
    for (var i = 0; i < artistsModel.count; ++i)
      if (artistsModel.get(i).id === id) {
        artistsModel.setProperty(i, "popularity", pop)
        break
      }
  }
  // A fresh search lands at the top of every section: the strip keeps
  // its own horizontal offset, reset alongside the page scroll.
  function resetStripOffset() {
    artistStrip.contentX = 0
  }

  Component.onCompleted: {
    group.readPrefs()
    group.ready = true
    group.applyGroup(host.searchRefreshMode)
  }
  // A removal can shift a later provider's group onto this delegate
  // (Repeater reuses items by index): its fold and SHOW ALL state belong
  // to the provider now in groupData, so the prefs re-read with it.
  onProviderIdChanged: if (group.ready)
    group.readPrefs()
  onGroupDataChanged: if (group.ready)
    group.applyGroup(host.searchRefreshMode)

  // The provider head: name, mark and sizes from its descriptor, count
  // or the honest error words + RETRY, and the whole head folds the
  // group. The descriptor's head style picks the furniture (TIDAL's
  // hover-lit accent head vs Apple's neutral one, issue #292); the
  // error furniture is the shipped Apple one (#241 / UI-05).
  Item {
    id: groupHead
    readonly property var provider: group.descriptor
    visible: group.headVisible
    width: parent.width
    height: group.accentHead ? 42 : 50
    Row {
      anchors.left: parent.left
      anchors.bottom: parent.bottom
      anchors.bottomMargin: 10
      spacing: 8
      ExpandChevron {
        anchors.verticalCenter: parent.verticalCenter
        open: !group.collapsed
        hovered: groupHeadMa.containsMouse
        tile: 20
        glyph: 14
        showTile: false
        stroke: groupHeadMa.containsMouse ? accent : textLo
      }
      Image {
        anchors.verticalCenter: parent.verticalCenter
        source: groupHead.provider ? groupHead.provider.logo : ""
        width: groupHead.provider ? groupHead.provider.logo_header_width : 0
        height: groupHead.provider ? groupHead.provider.logo_header_height : 0
        fillMode: Image.PreserveAspectFit
        smooth: true
        cache: true
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: groupHead.provider ? String(groupHead.provider.name).toUpperCase() : ""
        color: group.accentHead ? (groupHeadMa.containsMouse ? textHi : accent) : textHi
        font.pixelSize: 15
        font.bold: true
        font.letterSpacing: 1
      }
    }
    Text {
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      anchors.bottomMargin: 11
      visible: !group.errorStands
      textFormat: Text.PlainText
      text: group.rowCount + (group.rowCount === 1 ? " result" : " results")
      color: textDim
      font.family: mono
      font.pixelSize: 10
    }
    Text {
      objectName: "searchGroupError"
      // The words exist only where the group does; a refresh landing
      // after the provider was switched off cannot mount one.
      visible: group.errorStands
      anchors.left: parent.left
      anchors.leftMargin: 28
      // The retry's own spot, reserved: a sibling declared below
      // this text cannot be referenced by its anchor.
      anchors.right: parent.right
      anchors.rightMargin: 96
      anchors.bottom: parent.bottom
      anchors.bottomMargin: 10
      textFormat: Text.PlainText
      elide: Text.ElideRight
      text: group.errorText
      color: gold
      font.pixelSize: 12
    }
    SpecBtn {
      objectName: "searchGroupRetry"
      visible: group.errorStands
      compact: true
      label: "RETRY"
      anchors.right: parent.right
      anchors.rightMargin: 8
      anchors.bottom: parent.bottom
      anchors.bottomMargin: 6
      z: 2
      onClicked: if (host.lastSearchQuery !== "")
        host.submitSearch(host.lastSearchQuery)
    }
    Rectangle {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      height: 2
      color: group.accentHead ? accentDim : outline
    }
    MouseArea {
      id: groupHeadMa
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: group.toggleCollapsed()
    }
  }

  // TOP RESULT: the provider's own best match, pinned above every
  // section of the mixed All view (TIDAL answers one; a provider that
  // does not pins nothing). The item still sits in its section below:
  // this is a pointer, not a move.
  SectionHeader {
    id: topHead
    opacity: host.searchReveal
    visible: group.topVisible
    label: "TOP RESULT"
  }
  Repeater {
    id: topRep
    model: group.topRow !== null ? [group.topRow] : []
    delegate: Loader {
      id: topLd
      required property var modelData
      visible: group.topVisible
      width: parent.width
      asynchronous: host.searchBuilding
      opacity: host.searchReveal
      onLoaded: host._searchBuildTick()
      sourceComponent: topLd.modelData.kind === "album" ? topAlbumComp : topLd.modelData.kind === "playlist" ? topPlaylistComp : topTrackComp
      Component {
        id: topAlbumComp
        AlbumBlock {
          host: group.host
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
        }
      }
      Component {
        id: topTrackComp
        TrackRow {
          host: group.host
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
          albumId: topLd.modelData.album_id || ""
        }
      }
      Component {
        id: topPlaylistComp
        PlaylistBlock {
          host: group.host
          plId: topLd.modelData.id
          title: topLd.modelData.title
          creator: topLd.modelData.creator || ""
          art: topLd.modelData.art
          trackCount: topLd.modelData.tracks || 0
        }
      }
    }
  }

  // ARTISTS. The strip is the horizontal shelf the provider's payload
  // asks for (TIDAL); every other provider flows and caps at the mixed
  // view's five with SHOW ALL, as Apple's always has. Gating the two
  // layouts' Loaders keeps exactly one set active, so the build veil's
  // one-tick-per-artist count stays balanced.
  SectionHeader {
    id: artistsHead
    opacity: host.searchReveal
    visible: group.sectionVisible("artists")
    label: "ARTISTS"
    count: artistsModel.count
  }
  Flickable {
    id: artistStrip
    visible: group.sectionVisible("artists") && group.stripArtists && host.filterType === "all" && !group.isExpanded("artists")
    width: parent.width
    height: artistRow.height
    contentWidth: artistRow.width
    contentHeight: artistRow.height
    clip: true
    flickableDirection: Flickable.HorizontalFlick
    boundsBehavior: Flickable.StopAtBounds
    readonly property real cardW: 200
    Row {
      id: artistRow
      spacing: 12
      Repeater {
        model: artistsModel
        delegate: Loader {
          width: artistStrip.cardW
          // Reserve a fixed cell (width + 142) while the async Loader is
          // still empty (item null) so the strip does not collapse behind
          // the build veil; snap to the card's exact height once loaded.
          height: item ? item.implicitHeight : width + 142
          // Live only in strip mode, so exactly one of the strip and the
          // grid instantiates its cards (see above).
          active: group.stripArtists && host.filterType === "all" && !group.isExpanded("artists")
          asynchronous: host.searchBuilding
          opacity: host.searchReveal
          onLoaded: host._searchBuildTick()
          sourceComponent: ArtistSearchCard {
            host: group.host
            aArt: model.art
            aName: model.name
            aPop: model.popularity
            aId: model.id
          }
        }
      }
    }
    // Vertical wheel scrolls the page, sideways wheel/trackpad
    // scrolls the strip (shared with the browse shelves).
    ShelfWheelRedirect {
      pane: group.resultsPane
    }
    ShelfEdgeFades {}
  }
  Flow {
    id: artistFlow
    visible: group.sectionVisible("artists") && !(group.stripArtists && host.filterType === "all" && !group.isExpanded("artists"))
    width: parent.width
    spacing: 12
    property int cols: Math.max(1, Math.floor((width + spacing) / (190 + spacing)))
    property real cardW: (width - (cols - 1) * spacing) / cols
    Repeater {
      model: artistsModel
      delegate: Loader {
        // The strip layout uses the grid only when expanded or
        // filtered, where every row shows; a flow provider caps at
        // the mixed view's five until SHOW ALL.
        visible: group.stripArtists ? true : host.searchRowVisible("artists", artistsModel.count, index, group.isExpanded("artists"))
        width: artistFlow.cardW
        height: item ? item.implicitHeight : width + 142
        // Complement of the strip: live only when NOT in strip mode.
        active: group.stripArtists ? !(host.filterType === "all" && !group.isExpanded("artists")) : true
        asynchronous: host.searchBuilding
        opacity: host.searchReveal
        onLoaded: host._searchBuildTick()
        sourceComponent: ArtistSearchCard {
          host: group.host
          aArt: model.art
          aName: model.name
          aPop: model.popularity
          aId: model.id
        }
      }
    }
  }
  ShowAllLabel {
    host: group.host
    objectName: "artistsShowAll"
    opacity: host.searchReveal
    sectionTop: artistsHead
    // Offer SHOW ALL only when there is more to reveal: the strip's
    // overflow, or the flow's five-row cap. The count gate is what the
    // sections get from sectionVisible(); without it the expanded flag
    // (pref-backed) would keep this label on screen over an empty page.
    visible: group.sectionVisible("artists") && host.filterType === "all" && artistsModel.count > 0 && (group.isExpanded("artists") || (group.stripArtists ? artistStrip.contentWidth > artistStrip.width + 1 : artistsModel.count > 5))
    expanded: group.isExpanded("artists")
    count: artistsModel.count
    onToggled: group.toggleExpanded("artists")
  }

  // ALBUMS
  SectionHeader {
    id: albumsHead
    opacity: host.searchReveal
    visible: group.sectionVisible("albums")
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
      // SHOW ALL; the delegate still loads (and fires its build-veil
      // tick) while hidden, so the one-tick-per-item count stays
      // exact.
      visible: !group.collapsed && host.searchRowVisible("albums", albumsModel.count, index, group.isExpanded("albums"))
      width: parent.width
      asynchronous: host.searchBuilding
      opacity: host.searchReveal
      onLoaded: host._searchBuildTick()
      sourceComponent: AlbumBlock {
        host: group.host
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
      }
    }
  }
  SearchSectionMore {
    host: group.host
    section: "albums"
    sectionTop: albumsHead
    count: albumsModel.count
    expanded: group.isExpanded("albums")
    group: group
  }

  // TRACKS
  SectionHeader {
    id: tracksHead
    opacity: host.searchReveal
    visible: group.sectionVisible("tracks")
    label: "TRACKS"
    count: tracksModel.count
  }
  Repeater {
    model: tracksModel
    delegate: Loader {
      visible: !group.collapsed && host.searchRowVisible("tracks", tracksModel.count, index, group.isExpanded("tracks"))
      width: parent.width
      asynchronous: host.searchBuilding
      opacity: host.searchReveal
      onLoaded: host._searchBuildTick()
      sourceComponent: TrackRow {
        host: group.host
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
        albumId: model.album_id || ""
      }
    }
  }
  SearchSectionMore {
    host: group.host
    section: "tracks"
    sectionTop: tracksHead
    count: tracksModel.count
    expanded: group.isExpanded("tracks")
    group: group
  }

  // VIDEOS: art-first results, 16:9 thumbnails at grid size, with the
  // title, artist, release date and a full download button reading
  // underneath. Cells are sized from the section width, so the column
  // count follows the window.
  SectionHeader {
    id: videosHead
    opacity: host.searchReveal
    visible: group.sectionVisible("videos")
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
        visible: !group.collapsed && host.searchRowVisible("videos", videosModel.count, index, group.isExpanded("videos"), videoGrid.cap)
        width: videoGrid.cellW
        height: Math.round(videoGrid.cellW * 9 / 16) + 54
        asynchronous: host.searchBuilding
        opacity: host.searchReveal
        onLoaded: host._searchBuildTick()
        sourceComponent: VideoCell {
          host: group.host
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
        }
      }
    }
  }
  SearchSectionMore {
    host: group.host
    section: "videos"
    sectionTop: videosHead
    count: videosModel.count
    expanded: group.isExpanded("videos")
    group: group
    cap: videoGrid.cap
  }

  // PLAYLISTS
  SectionHeader {
    id: playlistsHead
    opacity: host.searchReveal
    visible: group.sectionVisible("playlists")
    label: "PLAYLISTS"
    count: playlistsModel.count
  }
  Repeater {
    model: playlistsModel
    delegate: Loader {
      visible: !group.collapsed && host.searchRowVisible("playlists", playlistsModel.count, index, group.isExpanded("playlists"))
      width: parent.width
      asynchronous: host.searchBuilding
      opacity: host.searchReveal
      // Reserve the collapsed row's height while the async build
      // runs (same rationale as the artist strip's fixed cell):
      // without it the section collapses to zero and pops open as
      // each row lands.
      height: item ? item.implicitHeight : 64
      onLoaded: host._searchBuildTick()
      sourceComponent: PlaylistBlock {
        host: group.host
        plId: model.id
        title: model.title
        creator: model.creator || ""
        art: model.art
        trackCount: model.tracks
      }
    }
  }
  SearchSectionMore {
    host: group.host
    section: "playlists"
    sectionTop: playlistsHead
    count: playlistsModel.count
    expanded: group.isExpanded("playlists")
    group: group
  }

  // MIXES
  SectionHeader {
    id: mixesHead
    opacity: host.searchReveal
    visible: group.sectionVisible("mixes")
    label: "MIXES"
    count: mixesModel.count
  }
  Repeater {
    model: mixesModel
    delegate: Loader {
      visible: !group.collapsed && host.searchRowVisible("mixes", mixesModel.count, index, group.isExpanded("mixes"))
      width: parent.width
      height: 66
      asynchronous: host.searchBuilding
      opacity: host.searchReveal
      onLoaded: host._searchBuildTick()
      sourceComponent: Rectangle {
        radius: 10
        color: surface
        border.color: border1
        RowLayout {
          anchors.fill: parent
          anchors.margins: 10
          spacing: 13
          Art {
            host: group.host
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
          DownloadButton {
            host: group.host
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
    host: group.host
    section: "mixes"
    sectionTop: mixesHead
    count: mixesModel.count
    expanded: group.isExpanded("mixes")
    group: group
  }
}

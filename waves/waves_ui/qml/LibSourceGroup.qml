import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// One My Music source group (issue #259): everything one provider's saved
// shelves need, and nothing provider-specific. The strip, its labels and
// the sort come from the source descriptor's categories; the panes are the
// app's neutral shelf shapes, each keep-alive; every page is fetched and
// every row built through the source's OWN provider
// (waves.loadLibrary(source, category) -> the provider's favorites_page /
// row_for), so a provider that later declares FAVORITES renders here with
// no edit to this file.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.appendMedia / host.appendPlain / host.fill / host.fillMedia /
//   host.fmtMs / host.hoverPrefetch / host.hoverPrefetchCancel /
//   host.libSortLabels / host.libSortOptions / host.libraryCategory /
//   host.libraryOpen / host.openLibrarySorted / host.openVideo /
//   host.previewPosition / host.pvSt / host.stopPreview / host.togglePreview
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
ColumnLayout {
  id: group
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property real btnTrack: 0              // label letter-spacing
  readonly property color divider: "#22262d"
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color surface2: "#191c22"   // hover / nested
  readonly property color surface3: "#1d2128"   // art bg / unlit meter / inset
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)

  property var sourceData: ({})
  property bool primary: false
  readonly property string sourceId: String(sourceData.id || "")
  readonly property string sourceLabel: String(sourceData.label || "")
  readonly property var categories: sourceData.categories || []
  // The visible shelf. Keep-alive: switching only changes which pane
  // shows, and every pane keeps its rows, expansion and scroll for the
  // session (an account flip clears them).
  property string category: ""
  // Infinite scroll per category: whether more pages exist, whether one
  // is in flight for the visible pane, and the armed pin for a quiet
  // revalidate's refill (a sort change or a fresh load disarms it).
  property var hasMore: ({})
  property bool loadingMore: false
  property bool pinRefill: false
  // Per-category sort, {cat: {key, asc}}: the bridge holds the same
  // choice for the fetch order, and only applySort mutates either.
  property var sort: ({})
  // This source's "Home" landing shelves (Browse-shaped, account-scoped).
  property var homeSections: []
  // The drilled-into playlist folder: per source, because the folder
  // tree is the provider's own read.
  property var folderStack: []
  property string currentFolder: ""

  Layout.fillWidth: true
  Layout.fillHeight: true
  spacing: 0

  // The keep-alive panes' models: one set per group instance, so a
  // second source's rows never land in the first source's lists.
  ListModel {
    id: albumsModel
  }
  ListModel {
    id: tracksModel
  }
  ListModel {
    id: artistsModel
  }
  ListModel {
    id: playlistsModel
  }
  ListModel {
    id: mixesModel
  }
  ListModel {
    id: videosModel
  }
  // The drilled-into folder's rows. Its own model on purpose: a
  // background revalidate of the playlists tab refills the six models
  // above and must not wipe the folder the user is standing in.
  ListModel {
    id: folderModel
  }

  Component.onCompleted: {
    // Start where the root expects the primary group, or at the first
    // shelf this source can fill -- and if the category the root
    // remembers is not one THIS source declares (a different source
    // became primary), its first shelf, so the strip is never blank.
    var wanted = group.primary ? String(host.libraryCategory || "") : ""
    group.category = group.hasCategory(wanted) ? wanted : (group.categories.length ? String(group.categories[0].id) : "")
    // A group that appears while the pane is open (a second source
    // signs in) loads its shelf too, so it is not a blank pane.
    if (host.libraryOpen)
      group.select(group.category)
  }
  onCategoryChanged: if (group.primary)
    host.libraryCategory = group.category

  function modelFor(cat) {
    // "folder" names the drill-in's own model (the playlists pane's
    // second view); the rest are the shelf panes' models.
    return cat === "albums" ? albumsModel : cat === "tracks" ? tracksModel : cat === "artists" ? artistsModel : cat === "playlists" ? playlistsModel : cat === "mixes" ? mixesModel : cat === "videos" ? videosModel : cat === "folder" ? folderModel : null
  }
  function viewFor(cat) {
    // "home" is a pane too (the scroll dressing follows it, and it is
    // the pane a fresh group shows); "folder" has its own view inside
    // the playlists pane.
    return cat === "home" ? homePane : cat === "albums" ? albumsList : cat === "tracks" ? tracksList : cat === "artists" ? artistsGrid : cat === "playlists" ? playlistsList : cat === "mixes" ? mixesList : cat === "videos" ? videosList : null
  }
  function hasCategory(cat) {
    for (var i = 0; i < group.categories.length; ++i)
      if (String(group.categories[i].id) === String(cat))
        return true
    return false
  }
  function isMedia(cat) {
    return cat === "albums" || cat === "tracks" || cat === "videos"
  }
  // `host.`-qualified for the page helpers: this component's own
  // `fill` would otherwise shadow the host's model filler.
  function fill(cat, items) {
    var m = group.modelFor(cat)
    if (m) {
      if (group.isMedia(cat))
        host.fillMedia(m, items)
      else
        host.fill(m, items)
    }
  }
  function append(cat, items) {
    var m = group.modelFor(cat)
    if (m) {
      if (group.isMedia(cat))
        host.appendMedia(m, items)
      else
        host.appendPlain(m, items)
    }
  }
  // Select a category and load it. "Home" is a self-contained,
  // Browse-shaped landing kept on screen: re-opening My Music shows the
  // shelves it already has, instantly. The backend serves the first load
  // from its disk snapshot and every visit triggers a quiet, throttled
  // revalidation (repainting only when the favourites changed), so an
  // app left running still stays current. Every other category pane is
  // keep-alive: a category that already has rows shows them as-is and
  // revalidates quietly (the backend repaints only on change, and the
  // refill pins the scroll spot); only a still-empty category does a
  // visible first load.
  function select(cat) {
    group.category = String(cat || "")
    group.loadingMore = false
    if (group.category === "home") {
      waves.loadHome(group.sourceId, group.homeSections.length > 0)
      return
    }
    var m = group.modelFor(group.category)
    if (m && m.count > 0) {
      group.pinRefill = true
      waves.loadLibrary(group.sourceId, group.category, true)
      return
    }
    group.pinRefill = false
    group.hasMore[group.category] = false
    waves.loadLibrary(group.sourceId, group.category)
  }
  // From a Home preview shelf: open the full list of that category,
  // forced newest-first so it lands on the items the preview showed.
  function selectSorted(cat) {
    var g = group.sortGet(cat)
    if (g.key === "date" && !g.asc) {
      group.select(cat)
      return
    }
    group.category = String(cat || "")
    group.loadingMore = false
    group.pinRefill = false
    group.hasMore[cat] = false
    var mm = group.modelFor(cat)
    if (mm)
      mm.clear()
    var m = {}
    for (var k in group.sort)
      m[k] = group.sort[k]
    m[cat] = {
      key: "date",
      asc: false
    }
    group.sort = m
    waves.setLibrarySort(group.sourceId, cat, "date", "desc")
  }
  function sortGet(cat) {
    var s = group.sort[cat]
    return s ? s : ({
        key: "date",
        asc: false
      })
  }
  function sortCurrentIndex(cat) {
    var opts = host.libSortOptions(cat), k = group.sortGet(cat).key
    for (var i = 0; i < opts.length; ++i)
      if (opts[i][1] === k)
        return i
    return 0
  }
  function applySort(cat, key, asc) {
    // Clone into a NEW object: mutating and reassigning the SAME
    // reference does not fire the var-property change signal, so no
    // binding on `sort` re-evaluates.
    var m = {}
    for (var k in group.sort)
      m[k] = group.sort[k]
    m[cat] = {
      key: key,
      asc: asc
    }
    group.sort = m
    group.pinRefill = false
    // a re-sorted list restarts at the top
    group.hasMore[cat] = false
    waves.setLibrarySort(group.sourceId, cat, key, asc ? "asc" : "desc")
  }
  // Called as the visible list scrolls; loads the next page well before
  // the bottom (~1.5 viewports early) so it feels endless.
  function maybeLoadMore(view, cat) {
    if (cat !== group.category || !group.hasMore[cat] || group.loadingMore)
      return
    if (view.count === 0 || view.contentHeight <= 0)
      return
    if (view.contentY + view.height > view.contentHeight - view.height * 1.5) {
      group.loadingMore = true
      waves.loadMoreLibrary(group.sourceId, cat)
    }
  }
  // A first page (or a quiet revalidate that found changes) landed for
  // this source.
  function applyLoaded(cat, items, more) {
    group.hasMore[cat] = more
    // A load for a category the user already left still lands in that
    // category's own (hidden, keep-alive) pane: returning to it later
    // is then instant. Only the ACTIVE pane needs the flags and the
    // scroll pinning.
    if (cat !== group.category) {
      group.fill(cat, items)
      return
    }
    group.loadingMore = false
    // A quiet revalidate that actually changed the rows replaces them
    // under the user; pin the spot across the refill. Sort changes and
    // fresh loads disarmed the pin, so those still land at the top.
    var v = group.viewFor(cat)
    var keepY = (group.pinRefill && v && v.visible && !v.moving && v.contentY > 0) ? v.contentY : -1
    group.fill(cat, items)
    if (keepY >= 0) {
      v.pendingY = keepY
      v.applyRestore()
    } else if (v) {
      // A restarted list (fresh load, new sort order) begins at the
      // top. Explicit, because a clear+refill leaves the old
      // contentY in place when the new content is just as tall.
      v.pendingY = -1
      v.contentY = 0
    }
  }
  function applyMore(cat, items, more) {
    if (cat !== group.category)
      return
    group.hasMore[cat] = more
    group.loadingMore = false
    group.append(cat, items)
  }
  // This source's Home landing answered. Only populate when the load
  // actually returned shelves: an empty result (a transient fetch
  // failure) must not wipe shelves already on screen, and a still-empty
  // first load leaves the pane blank until the next visit retries.
  function applyHome(sections) {
    group.loadingMore = false
    // Home is one self-contained landing
    if (sections && sections.length)
      group.homeSections = sections
  }
  // The account flipped: every keep-alive pane here holds the previous
  // account's rows for its whole life, so the flip is the one thing that
  // clears them.
  function clearPanes() {
    albumsModel.clear()
    tracksModel.clear()
    artistsModel.clear()
    playlistsModel.clear()
    mixesModel.clear()
    videosModel.clear()
    folderModel.clear()
    group.homeSections = []
    group.hasMore = ({})
    group.loadingMore = false
    group.sort = ({})
    group.pinRefill = false
    group.folderStack = []
    group.currentFolder = ""
  }
  // The playlist-folder drill-in (the playlists pane's own view).
  function openFolder(fid, title) {
    var st = group.folderStack.slice()
    if (st.length)
      st[st.length - 1].y = folderList.contentY
    st.push({
      id: fid,
      title: title,
      y: 0
    })
    group.folderStack = st
    group.currentFolder = fid
    folderList.pendingY = 0
    waves.openPlaylistFolder(group.sourceId, fid)
  }
  function crumbTo(level) {
    if (level < 0) {
      group.folderStack = []
      group.currentFolder = ""
      return
    }
    var entry = group.folderStack[level]
    group.folderStack = group.folderStack.slice(0, level + 1)
    group.currentFolder = entry.id
    folderList.pendingY = (entry.y === undefined ? 0 : entry.y)
    waves.openPlaylistFolder(group.sourceId, entry.id)
  }
  function folderReset() {
    group.folderStack = []
    group.currentFolder = ""
    folderModel.clear()
  }
  function applyFolder(fid, rows, path) {
    // Stale guard: the user already moved to another folder (or back
    // to the root) while this answer was in flight.
    if (fid !== group.currentFolder)
      return
    host.fill(folderModel, rows)
    folderList.applyRestore()
  }

  // Header row: the group's own label (only when more than one source
  // contributes -- a lone source's rows ARE that source) and its category
  // strip, the sort and the direction toggle. The pane's title lives on
  // the Library section above, which is always present, so a group never
  // repeats it.
  RowLayout {
    Layout.fillWidth: true
    Layout.leftMargin: 22
    Layout.rightMargin: 22
    Layout.topMargin: 2
    Layout.bottomMargin: 6
    spacing: 14
    Text {
      objectName: "libSourceLabel"
      visible: group.sourceLabel !== ""
      textFormat: Text.PlainText
      text: group.sourceLabel
      color: textLo
      font.pixelSize: 12
      font.bold: true
      Layout.alignment: Qt.AlignVCenter
    }
    // Wrap the tab strip in a plain Item that carries Layout.fillWidth,
    // and flow against a DEFINITE width (parent.width). A Flow with
    // Layout.fillWidth directly hits a stale-width feedback loop and
    // wraps spuriously on narrower (but still valid) window sizes,
    // leaving a dead band under the tabs. This is the pattern the other
    // Flows in this file use.
    Item {
      Layout.fillWidth: true
      Layout.alignment: Qt.AlignVCenter
      implicitHeight: libTabsFlow.implicitHeight
      Flow {
        id: libTabsFlow
        objectName: "libTabsFlow"
        width: parent.width
        spacing: 8
        Repeater {
          model: group.categories
          delegate: LibChip {
            required property var modelData
            label: modelData.label
            on: group.category === modelData.id
            onPicked: group.select(modelData.id)
          }
        }
      }
    }
    // Sort (mirrors the Search sort); hidden on the Home landing,
    // which is already newest-first and merged across kinds.
    ComboBox {
      id: libSortBox
      // Kept in the layout on Home too (opacity/enabled, not
      // visible) so the header keeps the same height and the tabs
      // keep the same position on every tab. Toggling `visible`
      // here dropped ~40px and shifted the whole pane vertically
      // when switching to or from Home.
      opacity: group.category === "home" ? 0 : 1
      enabled: group.category !== "home"
      visible: group.hasCategory(group.category)
      Layout.alignment: Qt.AlignVCenter
      implicitHeight: 40
      implicitWidth: 160
      model: host.libSortLabels(group.category)
      // A Binding element (not an inline currentIndex) so the value
      // survives the control's own imperative write on selection.
      Binding {
        target: libSortBox
        property: "currentIndex"
        value: group.sortCurrentIndex(group.category)
        restoreMode: Binding.RestoreBindingOrValue
      }
      onActivated: {
        var opts = host.libSortOptions(group.category)
        group.applySort(group.category, opts[currentIndex][1], group.sortGet(group.category).asc)
      }
      background: Rectangle {
        radius: 8
        color: surface2
        border.color: libSortBox.popup.visible ? accent : outline
      }
      contentItem: Text {
        textFormat: Text.PlainText
        text: libSortBox.displayText
        color: textHi
        font.pixelSize: 14
        leftPadding: 14
        rightPadding: 28
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
      }
      indicator: ExpandChevron {
        x: libSortBox.width - 26
        y: (libSortBox.height - 18) / 2
        tile: 18
        glyph: 13
        showTile: false
        closedAngle: -90
        openAngle: 0
        stroke: host.libraryOpen ? accent : "transparent"
        open: libSortBox.popup.visible
      }
      delegate: ItemDelegate {
        width: libSortBox.width
        contentItem: Text {
          textFormat: Text.PlainText
          text: modelData
          color: textHi
          font.pixelSize: 14
          verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
          color: highlighted ? surface3 : surface2
        }
        highlighted: libSortBox.highlightedIndex === index
      }
      popup: Popup {
        y: libSortBox.height + 4
        width: libSortBox.width
        padding: 4
        implicitHeight: contentItem.implicitHeight + 8
        background: Rectangle {
          radius: 8
          color: surface2
          border.color: outline
        }
        contentItem: ListView {
          clip: true
          implicitHeight: contentHeight
          model: libSortBox.popup.visible ? libSortBox.delegateModel : null
          ScrollBar.vertical: ScrollBar {}
        }
      }
    }
    Rectangle {
      // Reserve its space on Home too, matching libSortBox above,
      // so the header height and tab positions never shift.
      opacity: group.category === "home" ? 0 : 1
      enabled: group.category !== "home"
      visible: group.hasCategory(group.category)
      Layout.alignment: Qt.AlignVCenter
      implicitHeight: 40
      implicitWidth: 40
      radius: 8
      color: surface2
      border.color: outline
      Text {
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: group.sortGet(group.category).asc ? "↑" : "↓"
        color: textHi
        font.family: mono
        font.pixelSize: 18
      }
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          var g = group.sortGet(group.category)
          group.applySort(group.category, g.key, !g.asc)
        }
      }
    }
  }

  // The source's shelves, one pane each, all keep-alive. The panes a
  // source cannot fill (per its categories) simply never render.
  Item {
    Layout.fillWidth: true
    Layout.fillHeight: true

    LibList {
      id: albumsList
      cat: "albums"
      model: albumsModel
      host: group
      delegate: AlbumBlock {
        host: group.host
        required property var model
        width: ListView.view.width
        albumId: model.id
        title: model.title
        artistName: model.artist
        artistId: ""
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
    LibList {
      id: tracksList
      cat: "tracks"
      model: tracksModel
      host: group
      delegate: TrackRow {
        host: group.host
        required property var model
        width: ListView.view.width
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
    // Artists as a compact card grid (the Search artist card, shrunk)
    // rather than tall full-width rows, so more fit on screen. Click
    // opens the artist scoped to the user's library.
    GridView {
      id: artistsGrid
      visible: group.category === "artists"
      anchors.fill: parent
      anchors.leftMargin: 22
      anchors.rightMargin: 22
      clip: true
      model: artistsModel
      property int cols: Math.max(3, Math.floor(width / 132))
      cellWidth: width > 0 ? Math.floor(width / cols) : 132
      // + name row + the preview row pinned to the card bottom
      cellHeight: cellWidth + 46
      cacheBuffer: 800
      reuseItems: true
      boundsBehavior: Flickable.StopAtBounds
      // Breathing space inside the scroll area (see BrowseScroll).
      header: Item {
        width: 1
        height: 8
      }
      ScrollBar.vertical: ScrollBar {}
      // Same revalidate scroll pinning as LibList (this grid is
      // the one category pane that isn't a LibList).
      property real pendingY: -1
      function applyRestore() {
        if (pendingY < 0)
          return
        var maxY = Math.max(0, contentHeight - height)
        contentY = Math.min(pendingY, maxY)
        if (maxY >= pendingY)
          pendingY = -1
      }
      onMovementStarted: pendingY = -1
      onContentYChanged: group.maybeLoadMore(artistsGrid, "artists")
      onContentHeightChanged: {
        applyRestore()
        group.maybeLoadMore(artistsGrid, "artists")
      }
      onHeightChanged: group.maybeLoadMore(artistsGrid, "artists")
      delegate: Item {
        id: agCell
        required property var model
        width: artistsGrid.cellWidth
        height: artistsGrid.cellHeight
        // Resting on a followed artist has the page ready
        // before the click (see hoverPrefetch).
        readonly property var prefetchCard: ({
            kind: "artist",
            id: "" + (model.id || ""),
            art: "" + (model.art || "")
          })
        HoverHandler {
          onHoveredChanged: hovered ? host.hoverPrefetch(agCell.prefetchCard) : host.hoverPrefetchCancel(agCell.prefetchCard)
        }
        Rectangle {
          anchors.fill: parent
          anchors.margins: 5
          radius: 10
          color: agMa.containsMouse ? surface2 : surface
          border.color: border1
          Column {
            anchors.fill: parent
            anchors.margins: 8
            spacing: 6
            Item {
              width: parent.width
              height: width
              Art {
                host: group.host
                anchors.centerIn: parent
                width: parent.width
                height: width
                hoverFx: true
                fxKind: "artist"
                fxId: "" + (model.id || "")
                url: model.art
                // The one place you browse artists you
                // follow should not be the one place that
                // cannot say what you already hold. A
                // child of the Art, so it takes the tilt
                // and the rounded clip with it.
                ArtistBadges {
                  host: group.host
                  bar: true
                  width: parent.width
                  anchors.bottom: parent.bottom
                  artistName: "" + (model.name || "")
                }
              }
            }
            Text {
              textFormat: Text.PlainText
              text: model.name
              color: textHi
              font.pixelSize: 12
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
            }
          }
          MouseArea {
            id: agMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: waves.loadArtistLibrary(model.id)
          }
          // compact preview row (the Browse card's control
          // line, shrunk): ▶ PREVIEW -> elapsed + · STOP, playing
          // this artist's top track via the shared preview
          // machinery. Declared after agMa so its clicks win
          // over the open-artist click underneath.
          Item {
            id: agPv
            readonly property string pst: host.pvSt("artist", "" + model.id)
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 8
            width: agPvRow.implicitWidth
            height: 16
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: host.togglePreview("artist", "" + model.id, 0)
            }
            Row {
              id: agPvRow
              anchors.verticalCenter: parent.verticalCenter
              spacing: 4
              Ico {
                visible: agPv.pst !== "loading"
                name: agPv.pst === "playing" ? "pause" : "play"
                color: agPv.pst === "error" ? red : accent
                size: 10
                anchors.verticalCenter: parent.verticalCenter
              }
              Text {
                textFormat: Text.PlainText
                text: agPv.pst === "" ? "PREVIEW" : agPv.pst === "loading" ? "[buffering]" : agPv.pst === "error" ? "RETRY" : host.fmtMs(host.previewPosition)
                color: agPv.pst === "error" ? red : accent
                font.family: agPv.pst === "playing" || agPv.pst === "paused" || agPv.pst === "loading" ? mono : uiFont
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: btnTrack
                anchors.verticalCenter: parent.verticalCenter
                property real breathe: 1
                opacity: agPv.pst === "loading" ? breathe : 1
                SequentialAnimation on breathe {
                  running: agPv.pst === "loading"
                  loops: Animation.Infinite
                  NumberAnimation {
                    from: 1.0
                    to: 0.3
                    duration: 520
                    easing.type: Easing.InOutSine
                  }
                  NumberAnimation {
                    from: 0.3
                    to: 1.0
                    duration: 520
                    easing.type: Easing.InOutSine
                  }
                }
              }
              Text {
                textFormat: Text.PlainText
                visible: agPv.pst === "playing" || agPv.pst === "paused"
                text: "· STOP"
                color: agStopMa.containsMouse ? red : textDim
                font.family: uiFont
                font.pixelSize: 9
                font.bold: true
                font.letterSpacing: btnTrack
                anchors.verticalCenter: parent.verticalCenter
                MouseArea {
                  id: agStopMa
                  anchors.fill: parent
                  anchors.margins: -3
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: host.stopPreview()
                }
              }
            }
          }
        }
      }
    }
    // Home: a Browse-shaped landing scoped to the account. Rendered
    // from homeSections (same shelf shape as Browse), so the app's own
    // art-forward ArtCard / TrackRow shelves render it. Under a
    // "Recently added" header sit two preview shelves, "Recent albums"
    // and "Recent tracks"; each heading drills into that full tab,
    // newest-first (openLibrarySorted).
    Flickable {
      id: homePane
      visible: group.category === "home"
      anchors.fill: parent
      anchors.leftMargin: 22
      anchors.rightMargin: 22
      clip: true
      contentWidth: width
      contentHeight: homeCol.height + 32
      ScrollBar.vertical: ScrollBar {}
      boundsBehavior: Flickable.StopAtBounds
      Column {
        id: homeCol
        // y matches the favourites lists' 8px in-scroll padding
        // exactly, or the content would jump vertically when
        // switching between the category tabs.
        y: 8
        width: homePane.width
        spacing: 20
        Text {
          visible: group.homeSections.length > 0
          textFormat: Text.PlainText
          text: "Recently added"
          color: textHi
          font.pixelSize: 20
          font.bold: true
        }
        Repeater {
          model: group.homeSections
          delegate: Column {
            id: homeSec
            required property var modelData
            readonly property string target: homeSec.modelData.target || ""
            width: homeCol.width
            spacing: 10
            // Clickable shelf heading: drills into the matching
            // My Music tab, newest-first, showing the full list
            // this shelf previews. The hit area hugs the text.
            Item {
              implicitWidth: headRow.implicitWidth
              implicitHeight: headRow.implicitHeight
              Row {
                id: headRow
                spacing: 6
                Text {
                  id: headText
                  textFormat: Text.PlainText
                  text: homeSec.modelData.title || ""
                  color: (headMouse.containsMouse && homeSec.target !== "") ? accent : textHi
                  font.pixelSize: 16
                  font.bold: true
                }
                Text {
                  visible: homeSec.target !== ""
                  anchors.verticalCenter: headText.verticalCenter
                  textFormat: Text.PlainText
                  text: "›"
                  color: headMouse.containsMouse ? accent : textLo
                  font.pixelSize: 18
                }
              }
              MouseArea {
                id: headMouse
                anchors.fill: parent
                hoverEnabled: true
                enabled: homeSec.target !== ""
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: host.openLibrarySorted(homeSec.modelData.source, homeSec.target)
              }
            }
            // Card shelf (Recent albums preview).
            ListView {
              visible: homeSec.modelData.rowKind === "cards"
              width: parent.width
              height: 250
              orientation: ListView.Horizontal
              spacing: 14
              clip: true
              boundsBehavior: Flickable.StopAtBounds
              // Local terms, not `visible` (effective visibility
              // tears cards down on tab leave, rebuilds them in
              // the returning click's turn; see the Browse shelves).
              model: homeSec.modelData.rowKind === "cards" ? homeSec.modelData.items : []
              delegate: ArtCard {
                host: group.host
                required property var modelData
                card: modelData
              }
              ShelfWheelRedirect {
                pane: homePane
              }
              ShelfEdgeFades {}
            }
            // Recent tracks (vertical list, reuses TrackRow).
            Column {
              visible: homeSec.modelData.rowKind === "tracks"
              width: parent.width
              Repeater {
                model: homeSec.modelData.rowKind === "tracks" ? homeSec.modelData.items : []
                delegate: TrackRow {
                  host: group.host
                  required property var modelData
                  width: homeCol.width
                  tId: modelData.id
                  kind: modelData.kind || "track"
                  title: modelData.title
                  artistName: modelData.artist || ""
                  artistId: modelData.artist_id || ""
                  album: modelData.album || ""
                  art: modelData.art || ""
                  year: "" + (modelData.year || "")
                  date: modelData.date || ""
                  duration: modelData.duration || ""
                  durationSec: modelData.duration_sec || 0
                  quality: modelData.quality || ""
                  popularity: modelData.popularity || 0
                  albumId: modelData.album_id || ""
                }
              }
            }
          }
        }
      }
    }
    LibList {
      id: playlistsList
      cat: "playlists"
      model: playlistsModel
      host: group
      // Hidden (state intact, scroll kept) while drilled into a
      // folder; the folder view below takes over.
      visible: group.category === "playlists" && group.folderStack.length === 0
      delegate: LibPlaylistRow {
        host: group.host
        folderHost: group
      }
    }
    // Drilled-into playlist folder: pinned breadcrumb strip + the
    // folder's rows (subfolders first). Served from the cached
    // sweep, so landing is instant and already positioned.
    Item {
      visible: group.category === "playlists" && group.folderStack.length > 0
      anchors.fill: parent
      anchors.leftMargin: 22
      anchors.rightMargin: 22
      Flow {
        id: plCrumbStrip
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: 8
        spacing: 6
        Rectangle {
          radius: 8
          implicitHeight: 26
          implicitWidth: crumbRootTx.implicitWidth + 20
          color: surface2
          border.color: border1
          Text {
            id: crumbRootTx
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: "Playlists"
            color: textLo
            font.pixelSize: 12
          }
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: group.crumbTo(-1)
          }
        }
        Repeater {
          model: group.folderStack
          delegate: Row {
            id: crumbSeg
            required property var modelData
            required property int index
            spacing: 6
            readonly property bool last: index === group.folderStack.length - 1
            Text {
              textFormat: Text.PlainText
              text: "›"
              color: textDim
              font.pixelSize: 13
              anchors.verticalCenter: parent.verticalCenter
            }
            Rectangle {
              radius: 8
              implicitHeight: 26
              implicitWidth: crumbTx.implicitWidth + 20
              color: crumbSeg.last ? accentCont : surface2
              border.color: crumbSeg.last ? accentDim : border1
              Text {
                id: crumbTx
                anchors.centerIn: parent
                textFormat: Text.PlainText
                text: crumbSeg.modelData.title
                color: crumbSeg.last ? accent : textLo
                font.pixelSize: 12
                font.bold: crumbSeg.last
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                enabled: !crumbSeg.last
                onClicked: group.crumbTo(crumbSeg.index)
              }
            }
          }
        }
      }
      ListView {
        id: folderList
        anchors.top: plCrumbStrip.bottom
        anchors.topMargin: 8
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        clip: true
        spacing: 8
        cacheBuffer: 800
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}
        header: Item {
          width: 1
          height: 8
        }
        footer: Item {
          width: 1
          height: 20
        }
        model: folderModel
        delegate: LibPlaylistRow {
          host: group.host
          folderHost: group
        }
        // Land already positioned (crumb-back restores the
        // saved offset before paint; a fresh drill-in lands at
        // 0): the no-visible-scroll rule.
        property real pendingY: -1
        function applyRestore() {
          if (pendingY < 0)
            return
          var maxY = Math.max(0, contentHeight - height)
          contentY = Math.min(pendingY, maxY)
          if (maxY >= pendingY)
            pendingY = -1
        }
        onContentHeightChanged: applyRestore()
      }
    }
    LibList {
      id: mixesList
      cat: "mixes"
      model: mixesModel
      host: group
      delegate: Rectangle {
        required property var model
        width: ListView.view.width
        height: 64
        radius: 10
        color: surface
        border.color: border1
        RowLayout {
          anchors.fill: parent
          anchors.margins: 10
          spacing: 13
          Art {
            host: group.host
            width: 44
            height: 44
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
    LibList {
      id: videosList
      cat: "videos"
      model: videosModel
      host: group
      delegate: Rectangle {
        required property var model
        width: ListView.view.width
        height: 50
        color: "transparent"
        Rectangle {
          anchors.bottom: parent.bottom
          width: parent.width
          height: 1
          color: divider
        }
        RowLayout {
          anchors.fill: parent
          anchors.leftMargin: 6
          anchors.rightMargin: 6
          spacing: 12
          VideoThumb {
            host: group.host
            url: model.art
            videoId: model.id
            vTitle: model.title
            vArtist: model.artist
          }
          ColumnLayout {
            Layout.fillWidth: true
            spacing: 1
            Text {
              textFormat: Text.PlainText
              text: model.title
              color: textHi
              font.pixelSize: 13
              elide: Text.ElideRight
              Layout.fillWidth: true
            }
            Text {
              textFormat: Text.PlainText
              text: model.artist
              color: textLo
              font.pixelSize: 12
              elide: Text.ElideRight
              Layout.fillWidth: true
            }
          }
          Text {
            textFormat: Text.PlainText
            text: model.duration
            color: textLo
            font.pixelSize: 12
            Layout.preferredWidth: 42
          }
          DownIcon {
            host: group.host
            mediaId: model.id
            onTap: function () {
              waves.downloadVideo(model.id)
            }
          }
        }
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          z: -1
          onClicked: host.openVideo(model.id, model.title, model.artist)
        }
      }
    }

    // No placeholder for a loaded-empty category: the pane is
    // transparent, so the ambient wave-loop background fills it on its
    // own, never a card or glyph that flashes in for a beat and fades
    // out.
  }
}

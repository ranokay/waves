import QtQuick
import QtQuick.Layouts
import "../../primitives" as Primitives
import "../../components"
import "../../primitives"
import "../catalog"

// One Browse content section (a card shelf, a track list, a link
// cloud, a drilled grid). Hoisted out of the pane so the landing and
// the drilled page can render the SAME component from two always-alive
// panes; `landing` replaces every "am I the landing?" read of the
// global page key, which cannot distinguish the panes now that both
// exist at once.
// `host` is Main.qml's root object, bound at both instantiations (the
// landing shelf's Loader and the drilled page's Repeater) and required
// so a missed binding fails at load.
// It reads through it:
//   host._browseAsyncBuild / host._browseCardStart / host._browseCardTick /
//   host._browsePageBuildTick / host._browsePageCardStart /
//   host._browsePageCardTick / host.browseCanGrow / host.browseGrow /
//   host.browseGrowKey / host.browseGrowing / host.browseHighlightId /
//   host.browseHighlightPending / host.browsePage / host.browsePageBuilding /
//   host.browseStyle / host.gridCols / host.legacyBrowseProvider /
//   host.openBrowseLink / host.openBrowseSection / host.openPlaylistsFolder
// The palette values are local copies of Main.qml's static literals, except textDim which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Column {
  id: bsec
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — textDim binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color textDim: Primitives.Palette.textDim
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  property var sec: null
  property int secIndex: 0
  property bool landing: false
  // A shelf a landing refresh appended: its cards incubate on their own
  // (no veil is up to count them).
  property bool late: false
  // The rows this section holds. A refresh or endless-scroll growth
  // rebuilds `sec` with the new items; the slot model below hands the views
  // stable slots so only the changed rows rebind and the appended ones
  // join at the end.
  readonly property var items: (sec && sec.items) || []
  // Rows that arrived with the section; everything past them is growth (a
  // 50-row fetch created inline is the freeze again). The caller marks the
  // boundary as it grows the section.
  readonly property int baseCount: sec && sec.base !== undefined ? sec.base : bsec.items.length
  // One slot per row. The views take THIS model, never the array: a JS
  // array handed to a view is a reset on every change (every row torn down
  // and rebuilt), while a model that only grows appends delegates at the
  // end and leaves the rows above alone. Filled from handlers, never from a
  // binding: a model binding that appended as it was evaluated could run
  // inside the column's own layout pass (the rows it created changed the
  // heights being positioned), after which the column stayed at height 0
  // and the page showed nothing.
  ListModel {
    id: bsecSlots
  }
  property int _slotN: 0
  // The rows before the latest trim, for a slot a shorter row no longer
  // covers: its card binding still fires around the trim, and reading past
  // the new array's end would put the dying card on undefined for that
  // instant.
  readonly property var _itemsHeld: ({
      prev: [],
      cur: []
    })
  function syncSlots() {
    var n = bsec.items.length
    if (bsec._itemsHeld.cur.length > n)
      bsec._itemsHeld.prev = bsec._itemsHeld.cur
    bsec._itemsHeld.cur = bsec.items
    // A shorter section drops its trailing slots only: the rows that remain
    // keep their cards.
    if (bsec._slotN > n) {
      bsecSlots.remove(n, bsec._slotN - n)
      bsec._slotN = n
    }
    while (bsec._slotN < n) {
      bsecSlots.append({
        slot: bsec._slotN
      })
      bsec._slotN++
    }
  }
  onItemsChanged: bsec.syncSlots()
  // One counting path for both card views: a card created while a veil is
  // up joins its count and reports in when it lands (or goes down mid-
  // build, which must not pin the veil). A shelf a refresh appended is not
  // part of the build: its cards incubate and join no count, so a refresh
  // landing mid-build can neither extend nor complete that build.
  function _cardCreated(loader) {
    if (bsec.landing)
      loader.counted = !bsec.late && host._browseCardStart(loader.asynchronous)
    else
      loader.counted = host._browsePageCardStart(loader.asynchronous)
  }
  function _cardLanded(loader) {
    if (bsec.landing)
      host._browseCardTick(loader.counted)
    else
      host._browsePageCardTick(loader.counted)
    loader.counted = false
  }
  Component.onCompleted: {
    bsec.syncSlots()
    // A list view applies an insert on its next polish; applied now, the
    // cards exist inside the section's own creation, where the build veils
    // count them. A card created a frame later would join the count after
    // the section had already reported in.
    if (consoleShelf.model)
      consoleShelf.forceLayout()
    if (artShelf.model)
      artShelf.forceLayout()
    // A drilled section is one unit of its page's veil. The report is
    // deferred one turn: the shelves are ListViews, so their visible
    // delegates (which join the veil count as they are created) only exist
    // after the view's own polish; ticking here made the count complete
    // before a single card had joined it and the veil dropped early.
    if (!bsec.landing)
      Qt.callLater(bsec._reportSection)
  }
  function _reportSection() {
    if (consoleShelf.model)
      consoleShelf.forceLayout()
    if (artShelf.model)
      artShelf.forceLayout()
    host._browsePageBuildTick()
  }
  // Landing arrangement (issue #600): the caller owns the persisted state.
  // An arranged section keeps its header (and these controls) and hides its
  // body while collapsed; hide and move are signals the landing handles.
  property bool arrangeable: false
  property bool collapsed: false
  property bool canMoveUp: false
  property bool canMoveDown: false
  signal toggled
  signal hideRequested
  signal moveRequested(int delta)
  // The scroll pane and content column this section lives in, for
  // wheel redirection, row windowing and highlight centering.
  property Flickable pane: null
  property Item col: null
  // Where this section sits in the pane's scroll space. The row window
  // is measured from HERE, never from the top of the page: on the
  // landing a track shelf can sit thousands of pixels down a column of
  // twenty sections, and a window aimed with the page's own scroll
  // offset then lands far past the end of every short shelf, so no row
  // ever loads and the whole shelf shows as empty row cards. A landing
  // shelf hangs off an async Loader (parent) while a drilled one is the
  // delegate itself, hence the two shapes.
  readonly property real secTop: (landing ? (parent ? parent.y : 0) : y) + (col ? col.y : 0)
  // The first landing shelf becomes the art-first hero row: big
  // covers with the caption on the artwork.
  readonly property bool artStyle: host.browseStyle === "art"
  readonly property bool hero: artStyle && landing && secIndex === 0 && sec.rowKind === "cards"
  // A drilled "show more" page (one lone card section) lays its cards
  // out as a wrapping grid that scrolls with the page and re-flows on
  // resize, not a horizontal shelf.
  readonly property bool grid: sec.rowKind === "cards" && !landing && !(host.browsePage && host.browsePage.header) && ((host.browsePage && host.browsePage.sections) || []).length === 1
  // Suppress an empty/generic section headline on a drilled page, the
  // back bar already names it (avoids a stray "More" above e.g. the
  // Record Labels grid).
  readonly property bool showHeadline: ("" + (sec.title || "")).trim() !== ""
  // Every card shelf's headline opens the full listing: TIDAL's own
  // "show more" page when the row has one, else a local page built
  // from the row's items. Inert only on an already-drilled grid page
  // (self-link).
  readonly property bool headlinable: !grid && (!!sec.more || (sec.rowKind === "cards" && (sec.items || []).length > 0))
  function openListing() {
    if (sec.more)
      host.openBrowseLink(sec.more, sec.title || "More", String(sec.provider_id || bsec.host.legacyBrowseProvider))
    else
      host.openBrowseSection(sec)
  }
  spacing: 8
  // The landing's arrangement controls: move up / move down / hide, in the
  // app's mono data voice, shown only for an arranged landing. The chevron
  // covers collapse, so it is not repeated here.
  component ArrangeButton: Item {
    id: abtn
    property string label: ""
    property bool active: true
    signal tapped
    implicitWidth: abtnText.implicitWidth
    implicitHeight: 16
    Text {
      id: abtnText
      textFormat: Text.PlainText
      anchors.centerIn: parent
      text: abtn.label
      color: !abtn.active ? textDim : abtnMa.containsMouse ? accent : textLo
      font.family: mono
      font.pixelSize: 10
      font.bold: true
      font.letterSpacing: 1
    }
    TapAction {
      id: abtnMa
      anchors.fill: parent
      enabled: abtn.active
      accessibleLabel: abtn.label
      onTriggered: abtn.tapped()
    }
  }
  Component {
    id: arrangeControls
    Row {
      spacing: 12
      ArrangeButton {
        objectName: "browseArrangeUp"
        label: "UP"
        active: bsec.canMoveUp
        onTapped: bsec.moveRequested(-1)
      }
      ArrangeButton {
        objectName: "browseArrangeDown"
        label: "DOWN"
        active: bsec.canMoveDown
        onTapped: bsec.moveRequested(1)
      }
      ArrangeButton {
        objectName: "browseArrangeHide"
        label: "HIDE"
        onTapped: bsec.hideRequested()
      }
    }
  }
  SectionHeader {
    objectName: "browseSectionHeader"
    visible: !bsec.artStyle && bsec.showHeadline
    label: (bsec.sec.title || "More").toUpperCase()
    count: (bsec.sec.items || []).length
    openable: bsec.headlinable
    collapsible: bsec.arrangeable
    collapsed: bsec.collapsed
    onToggled: bsec.toggled()
    trailing: bsec.arrangeable ? arrangeControls : null
    onOpened: bsec.openListing()
  }
  RowLayout {
    visible: bsec.artStyle && bsec.showHeadline
    width: parent.width
    spacing: 10
    ExpandChevron {
      visible: bsec.arrangeable
      open: !bsec.collapsed
      hovered: bsecTitleMa.containsMouse
      tile: 20
      glyph: 14
      showTile: false
      stroke: bsecTitleMa.containsMouse ? accent : textLo
      Layout.alignment: Qt.AlignVCenter
      TapAction {
        objectName: "browseCollapseToggle"
        anchors.fill: parent
        accessibleLabel: (bsec.collapsed ? "Expand " : "Collapse ") + (bsec.sec.title || "More")
        onTriggered: bsec.toggled()
      }
    }
    Text {
      id: bsecTitle
      textFormat: Text.PlainText
      // "\u203a" marks headlines that open the full listing
      text: (bsec.sec.title || "More") + (bsec.headlinable ? "  \u203a" : "")
      color: bsecTitleMa.containsMouse ? "#ffffff" : textHi
      font.pixelSize: 17
      font.bold: true
      Layout.fillWidth: true
      elide: Text.ElideRight
      topPadding: 6
      TapAction {
        id: bsecTitleMa
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: Math.min(parent.width, parent.implicitWidth)
        enabled: bsec.headlinable
        accessibleLabel: "Open " + (bsec.sec.title || "More")
        onTriggered: bsec.openListing()
      }
    }
    Loader {
      active: bsec.arrangeable
      visible: active
      sourceComponent: arrangeControls
      Layout.alignment: Qt.AlignVCenter
    }
  }
  // full-listing wrap grid (drilled "show more" pages).
  // Width snaps to whole columns and the block centers in the pane,
  // so a half-column of dead space is split evenly left/right instead
  // of dumped on the right until the window grows enough to add
  // another column.
  Flow {
    id: bgridFlow
    visible: bsec.grid && !bsec.collapsed
    readonly property real cardW: bsec.artStyle ? 200 : 156
    spacing: bsec.artStyle ? 14 : 12
    readonly property int cols: host.gridCols(cardW, spacing, bsec.items.length, parent.width)
    width: cols * (cardW + spacing) - spacing
    x: Math.max(0, (parent.width - width) / 2)
    Repeater {
      model: bsec.grid ? bsecSlots : null
      delegate: Loader {
        id: bgridLd
        required property int index
        required property int slot
        readonly property var card: bsec.items[slot] || bsec._itemsHeld.prev[slot] || ({})
        // The card's own size, held while it incubates, so the grid keeps
        // its geometry (and the page its height).
        width: bgridFlow.cardW
        height: bsec.artStyle ? 246 : 236
        // Where this card sits in the pane's scroll space, from the grid's
        // own arithmetic (the Flow has not placed it when asynchronous is
        // read).
        readonly property real cardTop: bsec.secTop + bgridFlow.y + Math.floor(index / Math.max(1, bgridFlow.cols)) * (height + bgridFlow.spacing)
        // Growth cards incubate (a 50-card fetch created inline is the
        // freeze again), except the ones on the screen the page is shown
        // at: a Back to a grown listing builds what it lands on inline and
        // lets the rest come in. Behind a fresh drilled page's veil every
        // card incubates and reports in.
        readonly property bool inView: cardTop < bsec.pane.rowAnchorY + bsec.pane.height + height && cardTop + height > bsec.pane.rowAnchorY - height
        asynchronous: host.browsePageBuilding || (index >= bsec.baseCount && !inView)
        property bool counted: false
        Component.onCompleted: counted = host._browsePageCardStart(asynchronous)
        onLoaded: {
          host._browsePageCardTick(counted)
          counted = false
        }
        // A card taken down mid-build reports in as it goes, or the veil
        // waits for the guard.
        Component.onDestruction: host._browsePageCardTick(counted)
        sourceComponent: bsec.artStyle ? bgridArt : bgridConsole
        Component {
          id: bgridArt
          ArtCard {
            host: bsec.host
            card: bgridLd.card
          }
        }
        Component {
          id: bgridConsole
          BrowseCard {
            host: bsec.host
            card: bgridLd.card
          }
        }
      }
    }
  }
  // Grid footer: tells you whether more is coming or you've reached
  // the end, so a short editorial listing (e.g. 20 Top Albums)
  // doesn't read as "stuck" the way an endless genre listing keeps
  // flowing.
  Item {
    visible: bsec.grid && !bsec.collapsed
    width: parent.width
    height: 46
    readonly property bool loadingMore: !!(bsec.sec.data && host.browseGrowing[host.browseGrowKey(bsec.sec)])
    Row {
      anchors.centerIn: parent
      spacing: 10
      visible: parent.loadingMore || !host.browseCanGrow(bsec.sec)
      Rectangle {
        visible: !parent.parent.loadingMore
        anchors.verticalCenter: parent.verticalCenter
        width: 28
        height: 1
        color: border1
      }
      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: parent.parent.loadingMore ? "Loading more…" : (bsec.sec.items || []).length + " total"
        color: textDim
        font.family: mono
        font.pixelSize: 11
      }
      Rectangle {
        visible: !parent.parent.loadingMore
        anchors.verticalCenter: parent.verticalCenter
        width: 28
        height: 1
        color: border1
      }
    }
  }
  // horizontal card shelf, console (framed cards)
  ListView {
    id: consoleShelf
    objectName: "browseConsoleShelf"
    visible: !bsec.artStyle && !bsec.grid && bsec.sec.rowKind === "cards" && !bsec.collapsed
    width: parent.width
    height: 238
    orientation: ListView.Horizontal
    spacing: 12
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    // The model gate mirrors `visible`'s LOCAL terms, never
    // `visible` itself: that is EFFECTIVE visibility, so gating on
    // it tore down every card when the pane's ancestor hid (leaving
    // the tab) and rebuilt them all synchronously inside the
    // returning click's turn, ~180ms of jank on every switch back
    // to Browse. Keeping the cards alive across a hidden pane is
    // the whole point of the two-pane design.
    model: !bsec.artStyle && !bsec.grid && bsec.sec.rowKind === "cards" ? bsecSlots : null
    // Async per card, as the art shelf below (see its comment). A landing
    // shelf a refresh appended (`late`) and a shelf's growth rows incubate
    // on their own; a drilled page's cards incubate behind its veil and
    // report in.
    delegate: Loader {
      id: bcLd
      required property int index
      required property int slot
      readonly property var card: bsec.items[slot] || bsec._itemsHeld.prev[slot] || ({})
      width: 156
      height: 236
      asynchronous: bsec.landing ? (host._browseAsyncBuild || bsec.late || index >= bsec.baseCount) : host.browsePageBuilding
      property bool counted: false
      Component.onCompleted: bsec._cardCreated(bcLd)
      onLoaded: bsec._cardLanded(bcLd)
      Component.onDestruction: bsec._cardLanded(bcLd)
      sourceComponent: BrowseCard {
        host: bsec.host
        card: bcLd.card
      }
    }
    ShelfWheelRedirect {
      pane: bsec.pane
    }
    ShelfEdgeFades {}
    // endless scroll: reaching the shelf's right edge pulls the
    // row's next window from TIDAL
    onAtXEndChanged: if (atXEnd && count > 0)
      host.browseGrow(bsec.sec)
  }
  // horizontal card shelf, art-first (unframed covers)
  ListView {
    id: artShelf
    objectName: "browseArtShelf"
    visible: bsec.artStyle && !bsec.grid && bsec.sec.rowKind === "cards" && !bsec.collapsed
    width: parent.width
    height: bsec.hero ? 284 : 250
    orientation: ListView.Horizontal
    spacing: 14
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    // Local terms, not `visible` (see the console shelf above).
    model: bsec.artStyle && !bsec.grid && bsec.sec.rowKind === "cards" ? bsecSlots : null
    // Each card incubates behind an asynchronous Loader of the card's
    // fixed size, so the shelf's own creation is a row of empty slots
    // (cheap) and the cards fill in across frames. A shelf whose eight
    // cards were created inline took ~120ms in one atomic block at
    // launch (sampled live: the cards' bridge calls, each waiting its
    // turn behind the library scan), which the launch animation and
    // any later shelf scroll dropped frames on. The veil accounting
    // (host._browseCardStart / host._browseCardTick) keeps the landing
    // covered until the cards are in, not just the shelves; a landing
    // shelf a refresh appended, its growth rows, and every drilled
    // page's cards incubate the same way.
    delegate: Loader {
      id: acLd
      required property int index
      required property int slot
      readonly property var card: bsec.items[slot] || bsec._itemsHeld.prev[slot] || ({})
      readonly property real artSize: bsec.hero ? 280 : 200
      width: artSize
      height: bsec.hero ? artSize : artSize + 46
      asynchronous: bsec.landing ? (host._browseAsyncBuild || bsec.late || index >= bsec.baseCount) : host.browsePageBuilding
      property bool counted: false
      Component.onCompleted: bsec._cardCreated(acLd)
      onLoaded: bsec._cardLanded(acLd)
      Component.onDestruction: bsec._cardLanded(acLd)
      sourceComponent: ArtCard {
        host: bsec.host
        card: acLd.card
        hero: bsec.hero
      }
    }
    ShelfWheelRedirect {
      pane: bsec.pane
    }
    ShelfEdgeFades {}
    onAtXEndChanged: if (atXEnd && count > 0)
      host.browseGrow(bsec.sec)
  }
  // vertical track list (e.g. "New Tracks" on a genre page)
  Column {
    id: bsecRows
    visible: bsec.sec.rowKind === "tracks" && !bsec.collapsed
    width: parent.width
    Repeater {
      model: bsec.sec.rowKind === "tracks" ? bsecSlots : null
      // Fixed-height shells, content windowed: building every
      // TrackRow of a long playlist in one synchronous pass costs
      // 1.7s of frozen GUI per click (measured, budget 100ms).
      // The shells give the column its full geometry in the
      // assignment turn (so the scroll range and highlight
      // positions are exact from the first frame), then each
      // row's real content loads asynchronously. Only the screen
      // itself loads synchronously (the band's slack incubates:
      // building the slack inline stalled scrolling a long shelf
      // in ~100ms steps), plus the highlight target at any
      // distance, so what the user is actually looking at is
      // never a shell.
      delegate: Loader {
        id: btrLd
        required property int index
        required property int slot
        readonly property var row: bsec.items[slot] || bsec._itemsHeld.prev[slot]
        width: bsec.width
        height: 62   // TrackRow's fixed height
        readonly property bool hiRow: host.browseHighlightId !== "" && row.id === host.browseHighlightId
        // A screenful of rows: the live window's measure.
        readonly property real rps: Math.max(1, bsec.pane.height / 62)
        // Row 0 of THIS shelf, in the pane's scroll space, so the
        // window is expressed in this shelf's own row indices.
        readonly property real rowTop: bsec.secTop + bsecRows.y
        readonly property real anchorRow: (bsec.pane.rowAnchorY - rowTop) / 62
        // A shelf no longer than the window it would be measured
        // against is never worth windowing, and a short shelf is
        // exactly the case an aiming error can blank completely.
        readonly property bool shortSec: bsec.items.length <= 3 * rps
        // WINDOWED, not just incubated. Incubating every row
        // spread the build cost out but still left them all
        // alive: a 579-track playlist put ~76,000 items under
        // one Flickable (132 per built row, measured), and the
        // page stayed sluggish however long you sat on it,
        // because the cost is the live item tree, not the
        // build. Only the viewport plus two screens either side
        // is real; the rest stay 62px shells. The shell owns
        // the height, so unloading changes nothing about the
        // scroll range, the hold target or the endless-scroll
        // top-up, and two screens of slack is more than a flick
        // covers before the next band brings the following rows
        // in. The highlight row is exempt at any distance: it
        // arms browseHighlightPending and centres the page, so
        // it must exist even when the window is elsewhere.
        active: hiRow || shortSec || (index > anchorRow - 2 * rps && index < anchorRow + 3 * rps)
        asynchronous: {
          if (hiRow)
            return false
          // Behind a fresh drilled page's veil every in-view row
          // incubates too (and reports in like a card, see
          // counted below), so the payload's turn builds nothing
          // but shells.
          if (!bsec.landing && host.browsePageBuilding)
            return true
          // Only the screen itself builds inline; the slack rows
          // ahead of it incubate, and they are created two
          // screens early, so a scroll meets them built. The
          // anchor is floored to a ten-row band, so the screen
          // starts up to ten rows below it: the band reaches a
          // row above and ten rows plus one below the screen.
          // rowAnchorY, not contentY: this binding must not
          // re-evaluate on every scrolled frame (see there).
          return index < anchorRow - 1 || index > anchorRow + rps + 11
        }
        property bool counted: false
        Component.onCompleted: if (!bsec.landing && active)
          counted = host._browsePageCardStart(asynchronous)
        onLoaded: {
          host._browsePageCardTick(counted)
          counted = false
        }
        // A counted row that leaves the window before it lands (the layout
        // placed the section lower and the band moved under it) or goes
        // down with the page reports in as it goes: a long list kept its
        // veil up until the guard, waiting on rows that no longer existed.
        onActiveChanged: if (!active) {
          host._browsePageCardTick(counted)
          counted = false
        }
        Component.onDestruction: host._browsePageCardTick(counted)
        // Empty row card while the content incubates, so a
        // streaming list reads as rows filling in, not holes.
        Rectangle {
          anchors.fill: parent
          anchors.topMargin: 3
          anchors.bottomMargin: 3
          radius: 10
          color: surface
          border.color: border1
          visible: btrLd.status !== Loader.Ready
        }
        sourceComponent: TrackRow {
          id: btr
          host: bsec.host
          width: btrLd.width
          tId: btrLd.row.id
          kind: btrLd.row.kind || "track"
          title: btrLd.row.title
          artistName: btrLd.row.artist || ""
          artistId: btrLd.row.artist_id || ""
          album: btrLd.row.album || ""
          art: btrLd.row.art || ""
          year: "" + (btrLd.row.year || "")
          date: btrLd.row.date || ""
          duration: btrLd.row.duration || ""
          durationSec: btrLd.row.duration_sec || 0
          quality: btrLd.row.quality || ""
          popularity: btrLd.row.popularity || 0
          explicit: btrLd.row.explicit === true
          // Numbers only on item pages, where they're ordered
          // (album track #s / playlist positions), editorial
          // track shelves would all read "1".
          num: (!bsec.landing && host.browsePage && host.browsePage.header) ? (btrLd.row.num || 0) : 0
          albumId: btrLd.row.album_id || ""
          hi: btrLd.hiRow
          // Track click landed here: hide the page while it
          // lays out, center this row, then reveal, so the
          // scroll into place is never seen. onCompleted
          // fires before the first paint, so the page is
          // already hidden when this content would show at
          // the top.
          Component.onCompleted: if (btr.hi)
            host.browseHighlightPending = true
          Timer {
            interval: 120
            running: btr.hi
            onTriggered: {
              var y = btr.mapToItem(bsec.col, 0, 0).y - (bsec.pane.height - btr.height) / 2
              bsec.pane.contentY = Math.max(0, Math.min(y, bsec.pane.contentHeight - bsec.pane.height))
              host.browseHighlightPending = false
            }
          }
        }
      }
    }
  }
  // Sub-page links (genre / mood / decade / label tiles).
  // In art mode these are fixed-size tiles, so they use the SAME
  // centered, column-snapped, responsive geometry as the card grid,
  // one presentation across every drilled box view. Console mode
  // keeps the variable-width chip flow.
  Flow {
    visible: bsec.sec.rowKind === "links" && !bsec.collapsed
    readonly property bool tiled: bsec.artStyle
    readonly property real cardW: 200
    spacing: tiled ? 14 : 8
    readonly property int cols: host.gridCols(cardW, spacing, bsec.items.length, parent.width)
    width: tiled ? cols * (cardW + spacing) - spacing : parent.width
    x: tiled ? Math.max(0, (parent.width - width) / 2) : 0
    Repeater {
      model: bsec.sec.rowKind === "links" ? bsecSlots : null
      delegate: Loader {
        id: blinkLd
        required property int index
        required property int slot
        readonly property var row: bsec.items[slot] || bsec._itemsHeld.prev[slot] || ({})
        sourceComponent: bsec.artStyle ? blinkTile : blinkChip
        Component {
          id: blinkTile
          BrowseTile {
            host: bsec.host
            title: blinkLd.row.title
            path: blinkLd.row.path
            provider: String(blinkLd.row.provider_id || bsec.sec.provider_id || bsec.host.legacyBrowseProvider)
            idx: blinkLd.index
            plOnly: !!blinkLd.row.pl
          }
        }
        Component {
          id: blinkChip
          Rectangle {
            id: blink
            radius: 8
            implicitHeight: 30
            implicitWidth: blRow.implicitWidth + 26
            color: "transparent"
            border.color: border1
            Row {
              id: blRow
              anchors.centerIn: parent
              spacing: 7
              Rectangle {
                width: 6
                height: 6
                radius: 3
                anchors.verticalCenter: parent.verticalCenter
                color: textDim
              }
              Text {
                textFormat: Text.PlainText
                anchors.verticalCenter: parent.verticalCenter
                text: blinkLd.row.title
                color: textLo
                font.pixelSize: 13
              }
            }
            TapAction {
              anchors.fill: parent
              accessibleLabel: "Open " + (blinkLd.row.title || "category")
              focusRadius: 8
              // The link's own owner rides along; a drilled page's links have
              // none individually and inherit the page's provider.
              readonly property string owner: String(blinkLd.row.provider_id || bsec.sec.provider_id || bsec.host.legacyBrowseProvider)
              onTriggered: blinkLd.row.pl ? host.openPlaylistsFolder(blinkLd.row.path, blinkLd.row.title, owner) : host.openBrowseLink(blinkLd.row.path, blinkLd.row.title, owner)
            }
          }
        }
      }
    }
  }
}

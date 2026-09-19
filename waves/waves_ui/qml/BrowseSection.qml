import QtQuick

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
//   host.browseCanGrow / host.browseGrow / host.browseGrowing /
//   host.browseHighlightId / host.browseHighlightPending / host.browsePage /
//   host.browseStyle / host.gridCols / host.openBrowseLink /
//   host.openBrowseSection / host.openPlaylistsFolder
// Split out of Main.qml (#315 slice 7). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Column {
  id: bsec
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  property var sec: null
  property int secIndex: 0
  property bool landing: false
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
      host.openBrowseLink(sec.more, sec.title || "More")
    else
      host.openBrowseSection(sec)
  }
  spacing: 8
  SectionHeader {
    visible: !bsec.artStyle && bsec.showHeadline
    label: (bsec.sec.title || "More").toUpperCase() + (bsec.headlinable ? "  \u203a" : "")
    count: (bsec.sec.items || []).length
    MouseArea {
      anchors.fill: parent
      enabled: bsec.headlinable
      cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: bsec.openListing()
    }
  }
  Text {
    id: bsecTitle
    visible: bsec.artStyle && bsec.showHeadline
    textFormat: Text.PlainText
    // "\u203a" marks headlines that open the full listing
    text: (bsec.sec.title || "More") + (bsec.headlinable ? "  \u203a" : "")
    color: bsecTitleMa.containsMouse ? "#ffffff" : textHi
    font.pixelSize: 17
    font.bold: true
    width: parent.width
    elide: Text.ElideRight
    topPadding: 6
    MouseArea {
      id: bsecTitleMa
      anchors.left: parent.left
      anchors.top: parent.top
      anchors.bottom: parent.bottom
      width: Math.min(parent.width, parent.implicitWidth)
      enabled: bsec.headlinable
      hoverEnabled: enabled
      cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: bsec.openListing()
    }
  }
  // full-listing wrap grid (drilled "show more" pages).
  // Width snaps to whole columns and the block centers in the pane,
  // so a half-column of dead space is split evenly left/right instead
  // of dumped on the right until the window grows enough to add
  // another column.
  Flow {
    visible: bsec.grid
    readonly property real cardW: bsec.artStyle ? 200 : 156
    spacing: bsec.artStyle ? 14 : 12
    readonly property int cols: host.gridCols(cardW, spacing, (bsec.sec.items || []).length, parent.width)
    width: cols * (cardW + spacing) - spacing
    x: Math.max(0, (parent.width - width) / 2)
    Repeater {
      model: bsec.grid ? bsec.sec.items : []
      delegate: Loader {
        id: bgridLd
        required property var modelData
        sourceComponent: bsec.artStyle ? bgridArt : bgridConsole
        Component {
          id: bgridArt
          ArtCard {
            host: bsec.host
            card: bgridLd.modelData
          }
        }
        Component {
          id: bgridConsole
          BrowseCard {
            host: bsec.host
            card: bgridLd.modelData
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
    visible: bsec.grid
    width: parent.width
    height: 46
    readonly property bool loadingMore: !!(bsec.sec.data && host.browseGrowing[bsec.sec.data])
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
    visible: !bsec.artStyle && !bsec.grid && bsec.sec.rowKind === "cards"
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
    model: !bsec.artStyle && !bsec.grid && bsec.sec.rowKind === "cards" ? bsec.sec.items : []
    // Async per card, as the art shelf below (see its comment).
    delegate: Loader {
      id: bcLd
      required property var modelData
      width: 156
      height: 236
      asynchronous: bsec.landing && host._browseAsyncBuild
      Component.onCompleted: host._browseCardStart(asynchronous)
      onLoaded: host._browseCardTick(asynchronous)
      sourceComponent: BrowseCard {
        host: bsec.host
        card: bcLd.modelData
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
    visible: bsec.artStyle && !bsec.grid && bsec.sec.rowKind === "cards"
    width: parent.width
    height: bsec.hero ? 284 : 250
    orientation: ListView.Horizontal
    spacing: 14
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    // Local terms, not `visible` (see the console shelf above).
    model: bsec.artStyle && !bsec.grid && bsec.sec.rowKind === "cards" ? bsec.sec.items : []
    // Each card incubates behind an asynchronous Loader of the card's
    // fixed size, so the shelf's own creation is a row of empty slots
    // (cheap) and the cards fill in across frames. A shelf whose eight
    // cards were created inline took ~120ms in one atomic block at
    // launch (sampled live: the cards' bridge calls, each waiting its
    // turn behind the library scan), which the launch animation and
    // any later shelf scroll dropped frames on. The veil accounting
    // (host._browseCardStart / host._browseBuildTick) keeps the landing
    // covered until the cards are in, not just the shelves.
    delegate: Loader {
      id: acLd
      required property var modelData
      readonly property real artSize: bsec.hero ? 280 : 200
      width: artSize
      height: bsec.hero ? artSize : artSize + 46
      // Only while the landing itself builds asynchronously (behind
      // the veil): a synchronous in-place refresh, and every drilled
      // page, still creates its cards inline so nothing is watched
      // filling in.
      asynchronous: bsec.landing && host._browseAsyncBuild
      Component.onCompleted: host._browseCardStart(asynchronous)
      onLoaded: host._browseCardTick(asynchronous)
      sourceComponent: ArtCard {
        host: bsec.host
        card: acLd.modelData
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
    visible: bsec.sec.rowKind === "tracks"
    width: parent.width
    Repeater {
      model: bsec.sec.rowKind === "tracks" ? bsec.sec.items : []
      // Fixed-height shells, content windowed: building every
      // TrackRow of a long playlist in one synchronous pass costs
      // 1.7s of frozen GUI per click (measured, budget 100ms).
      // The shells give the column its full geometry in the
      // assignment turn (so the scroll range and highlight
      // positions are exact from the first frame), then each
      // row's real content loads asynchronously. Rows near the
      // viewport (or the spot a hold is armed for) and the
      // highlight target load synchronously, so what the user is
      // actually looking at is never a shell.
      delegate: Loader {
        id: btrLd
        required property var modelData
        required property int index
        width: bsec.width
        height: 62   // TrackRow's fixed height
        readonly property bool hiRow: host.browseHighlightId !== "" && modelData.id === host.browseHighlightId
        // A screenful of rows: the live window's measure.
        readonly property real rps: Math.max(1, bsec.pane.height / 62)
        // Row 0 of THIS shelf, in the pane's scroll space, so the
        // window is expressed in this shelf's own row indices.
        readonly property real rowTop: bsec.secTop + bsecRows.y
        readonly property real anchorRow: (bsec.pane.rowAnchorY - rowTop) / 62
        // A shelf no longer than the window it would be measured
        // against is never worth windowing, and a short shelf is
        // exactly the case an aiming error can blank completely.
        readonly property bool shortSec: (bsec.sec.items || []).length <= 3 * rps
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
          // A few rows of slack either side absorb the fact
          // that anchorRow moves in bands, not per pixel.
          // rowAnchorY, not contentY: this binding must not
          // re-evaluate on every scrolled frame (see there).
          return index < anchorRow - 8 || index > anchorRow + rps + 12
        }
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
          tId: btrLd.modelData.id
          kind: btrLd.modelData.kind || "track"
          title: btrLd.modelData.title
          artistName: btrLd.modelData.artist || ""
          artistId: btrLd.modelData.artist_id || ""
          album: btrLd.modelData.album || ""
          art: btrLd.modelData.art || ""
          year: "" + (btrLd.modelData.year || "")
          date: btrLd.modelData.date || ""
          duration: btrLd.modelData.duration || ""
          durationSec: btrLd.modelData.duration_sec || 0
          quality: btrLd.modelData.quality || ""
          popularity: btrLd.modelData.popularity || 0
          // Numbers only on item pages, where they're ordered
          // (album track #s / playlist positions), editorial
          // track shelves would all read "1".
          num: (!bsec.landing && host.browsePage && host.browsePage.header) ? (btrLd.modelData.num || 0) : 0
          albumId: btrLd.modelData.album_id || ""
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
    visible: bsec.sec.rowKind === "links"
    readonly property bool tiled: bsec.artStyle
    readonly property real cardW: 200
    spacing: tiled ? 14 : 8
    readonly property int cols: host.gridCols(cardW, spacing, (bsec.sec.items || []).length, parent.width)
    width: tiled ? cols * (cardW + spacing) - spacing : parent.width
    x: tiled ? Math.max(0, (parent.width - width) / 2) : 0
    Repeater {
      model: bsec.sec.rowKind === "links" ? bsec.sec.items : []
      delegate: Loader {
        id: blinkLd
        required property var modelData
        required property int index
        sourceComponent: bsec.artStyle ? blinkTile : blinkChip
        Component {
          id: blinkTile
          BrowseTile {
            host: bsec.host
            title: blinkLd.modelData.title
            path: blinkLd.modelData.path
            idx: blinkLd.index
            plOnly: !!blinkLd.modelData.pl
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
                text: blinkLd.modelData.title
                color: textLo
                font.pixelSize: 13
              }
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: blinkLd.modelData.pl ? host.openPlaylistsFolder(blinkLd.modelData.path, blinkLd.modelData.title) : host.openBrowseLink(blinkLd.modelData.path, blinkLd.modelData.title)
            }
          }
        }
      }
    }
  }
}

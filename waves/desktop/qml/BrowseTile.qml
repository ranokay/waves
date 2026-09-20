import QtQuick

// Tile for genre / mood / decade entries in the art-first layout. The
// artwork is a mosaic of real covers sampled from that page (drawn from
// different rows, Top Artists, New/Classic Albums, Essentials…, see
// backend _page_art_sample), streamed in after the landing loads and
// cached for a week. The sample holds up to 12 covers: four show at once
// and the tile slowly rotates one quadrant at a time through the rest,
// each tile on its own beat. Until (or unless) covers arrive, the tile
// falls back to the tone panel: wave glyphs from the WaveMark, or a big
// era numeral for "1950s"-style titles.
// `host` is Main.qml's root object, bound at both instantiations (the
// landing cloud's ListView and the All Playlists grid's) and required so
// a missed binding fails at load.
// It reads through it:
//   host.artFxLift / host.artFxTilt / host.artFxVariant / host.browseMoving /
//   host.browseTileArt / host.catPendingDl / host.catPendingPv / host.dlSt /
//   host.onScreen / host.openBrowseLink / host.openPlaylistsFolder
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: bt
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentContTx: "#86ffaa"   // text on accent container
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property real btnBorderW: 1.5
  readonly property real btnTrack: 0              // label letter-spacing
  readonly property color cyanDim: "#3a8d99"
  readonly property color goldCont: "#2a2008"
  readonly property color goldContTx: "#ffd27a"
  readonly property color goldDim: "#b07d18"
  readonly property color greenCont: "#08230f"
  readonly property color greenContTx: "#8bf0b8"
  readonly property color greenDim: "#2aa862"
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color redCont: "#2a0e0c"
  readonly property color surface3: "#1d2128"   // art bg / unlit meter / inset
  readonly property color textHi: "#e6e8ec"
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)

  property string title: ""
  property string path: ""
  property int idx: 0
  // Tile lives inside the Playlists folder view: drill into the
  // playlists-only grid instead of the full editorial page.
  property bool plOnly: false
  readonly property var tones: [[accentCont, accentDim, accentContTx], [goldCont, goldDim, goldContTx], ["#0a2126", cyanDim, "#9fdbe6"], [redCont, "#8a3a34", "#ffb3ad"], [greenCont, greenDim, greenContTx], [surface3, outline, textHi],]
  readonly property var tone: tones[idx % 6]
  readonly property string era: /^\d{4}s$/.test(title) ? "'" + title.substring(2) : ""
  readonly property var arts: host.browseTileArt[path] || []
  // 4+ covers -> 2x2 mosaic; 2-3 -> two half tiles; 1 -> full bleed.
  readonly property int artN: arts.length >= 4 ? 4 : arts.length >= 2 ? 2 : arts.length
  // Which pool index each visible cell shows; advanced one cell at a
  // time by the rotation timer once the pool is deeper than the grid.
  property var cells: [0, 1, 2, 3]
  property int _rotPtr: 3
  property int _rotCursor: 0
  onArtsChanged: {
    cells = [0, 1, 2, 3]
    _rotPtr = 3
    _rotCursor = 0
  }
  // Square, so the 2x2 cells are square too and album covers show whole
  // (a 90x48 cell was cropping every cover to a letterbox slice). Sized to
  // match the album art blocks (ArtCard.artSize), one art scale across
  // the browse cards, the drilled shelves, and these wayfinding tiles.
  width: 200
  height: 200
  radius: 12
  clip: true
  // Hover tilt at tile level: the whole mosaic (cells, scrim, title)
  // moves as one slab, matching the Art component's effect.
  property real fxRx: 0
  property real fxRy: 0
  property real fxLift: 1.0
  readonly property bool fxOn: host.artFxVariant !== "none"
  // Same rest-before-tilt arming as Art: a tile wall scrolling under a
  // stationary cursor must not spring every tile it drags past.
  property bool fxArmed: false
  function _fxAim(p) {
    var cx = width / 2, cy = height / 2
    fxRy = ((p.x - cx) / cx) * host.artFxTilt
    fxRx = -((p.y - cy) / cy) * host.artFxTilt
  }
  Timer {
    id: btFxArm
    interval: 90
    onTriggered: {
      if (!btFxHover.hovered)
        return
      bt.fxArmed = true
      bt.fxLift = host.artFxLift
      bt._fxAim(btFxHover.point.position)
    }
  }
  Behavior on fxRx {
    NumberAnimation {
      duration: 280
      easing.type: Easing.OutBack
    }
  }
  Behavior on fxRy {
    NumberAnimation {
      duration: 280
      easing.type: Easing.OutBack
    }
  }
  Behavior on fxLift {
    NumberAnimation {
      duration: 280
      easing.type: Easing.OutBack
    }
  }
  transform: [
    Rotation {
      origin.x: bt.width / 2
      origin.y: bt.height / 2
      axis: Qt.vector3d(1, 0, 0)
      angle: bt.fxRx
    },
    Rotation {
      origin.x: bt.width / 2
      origin.y: bt.height / 2
      axis: Qt.vector3d(0, 1, 0)
      angle: bt.fxRy
    },
    Scale {
      origin.x: bt.width / 2
      origin.y: bt.height / 2
      xScale: bt.fxLift
      yScale: bt.fxLift
    }
  ]
  HoverHandler {
    id: btFxHover
    enabled: bt.fxOn
    onHoveredChanged: {
      if (hovered)
        btFxArm.restart()
      else {
        btFxArm.stop()
        bt.fxArmed = false
        bt.fxRx = 0
        bt.fxRy = 0
        bt.fxLift = 1.0
      }
    }
    onPointChanged: if (bt.fxArmed)
      bt._fxAim(point.position)
  }
  gradient: Gradient {
    GradientStop {
      position: 0
      color: bt.tone[0]
    }
    GradientStop {
      position: 1
      color: Qt.darker(bt.tone[0], 1.45)
    }
  }
  border.width: 1
  border.color: btMa.containsMouse ? tone[2] : tone[1]
  // cover mosaic (clips to the tile's rounded corners)
  Repeater {
    model: bt.artN
    delegate: MosaicCell {
      required property int index
      x: bt.artN === 1 ? 0 : (index % 2) * bt.width / 2
      y: bt.artN <= 2 ? 0 : Math.floor(index / 2) * bt.height / 2
      width: bt.artN === 1 ? bt.width : bt.width / 2
      height: bt.artN <= 2 ? bt.height : bt.height / 2
      src: bt.arts[bt.cells[index]] || bt.arts[index] || ""
    }
  }
  // Slow rotation: every few seconds one cell crossfades to the next
  // unseen cover in the pool, each tile on its own beat (staggered
  // interval), paused while the window is unfocused, so the wall of
  // tiles feels alive without ever churning.
  Timer {
    interval: 5200 + (bt.idx % 7) * 1150
    repeat: true
    running: host.onScreen && !host.browseMoving && bt.visible && bt.arts.length > bt.artN && bt.artN > 0
    onTriggered: {
      var pool = bt.arts.length
      var n = bt.artN
      var next = (bt._rotPtr + 1) % pool
      var guard = 0
      var c = bt.cells.slice();
      // Scan only the VISIBLE cells: stale indices in the unused
      // tail (when artN < 4) would otherwise block covers forever
      // and, once the guard exhausted, let a duplicate on screen.
      var shown = c.slice(0, n)
      while (shown.indexOf(next) !== -1 && guard++ < pool)
        next = (next + 1) % pool
      if (shown.indexOf(next) !== -1)
        // pool too small to rotate cleanly
        return
      c[bt._rotCursor % n] = next
      bt._rotPtr = next
      bt._rotCursor = bt._rotCursor + 1
      bt.cells = c
    }
  }
  // scrim so the title stays readable over any artwork
  Rectangle {
    visible: bt.artN > 0
    anchors.fill: parent
    gradient: Gradient {
      GradientStop {
        position: 0
        color: "#c20a0c0f"
      }
      GradientStop {
        position: 0.55
        color: "#590a0c0f"
      }
      GradientStop {
        position: 1
        color: "#26000000"
      }
    }
  }
  // no-art fallback: the WaveMark's wave layers, or the era numeral
  Item {
    visible: bt.artN === 0
    anchors.fill: parent
    anchors.margins: 3
    clip: true
    Repeater {
      model: bt.era !== "" ? [] : [
        {
          yf: 0.48,
          px: 9,
          op: 0.26,
          pat: ".~-~..-~-.~..-~-."
        },
        {
          yf: 0.62,
          px: 12,
          op: 0.36,
          pat: "_.-~-._.,-~-._.-"
        },
        {
          yf: 0.76,
          px: 16,
          op: 0.50,
          pat: "_.-~^~-._.~^'~._"
        }
      ]
      delegate: Text {
        required property var modelData
        textFormat: Text.PlainText
        x: -8 - (bt.idx % 5) * 9   // stagger so neighbours don't sync
        y: Math.round(bt.height * modelData.yf)
        text: modelData.pat.repeat(4)
        font.family: mono
        font.pixelSize: modelData.px
        font.letterSpacing: -1
        // Foam-bright neutral: tone-on-tone glyphs vanish into the
        // darker containers, near-white reads evenly on every tile.
        color: textHi
        opacity: modelData.op
      }
    }
    Text {
      visible: bt.era !== ""
      textFormat: Text.PlainText
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      anchors.rightMargin: 4
      anchors.bottomMargin: -10
      text: bt.era
      font.family: mono
      font.pixelSize: 54
      font.bold: true
      color: bt.tone[2]
      opacity: 0.20
    }
  }
  Text {
    textFormat: Text.PlainText
    anchors.left: parent.left
    anchors.top: parent.top
    anchors.right: parent.right
    anchors.margins: 12
    text: bt.title
    color: bt.artN > 0 ? "#f2f4f7" : bt.tone[2]
    font.pixelSize: 17
    font.bold: true
    wrapMode: Text.Wrap
    maximumLineCount: 2
    elide: Text.ElideRight
  }
  MouseArea {
    id: btMa
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: bt.plOnly ? host.openPlaylistsFolder(bt.path, bt.title) : host.openBrowseLink(bt.path, bt.title)
  }
  // All Playlists folder chrome: the card-style hover strip (PREVIEW |
  // DOWNLOAD ALL), swapped for the live rollup button + badge once the
  // category is downloading. HoverHandler, not btMa.containsMouse: the
  // strip's own MouseAreas would steal the hover and flicker the strip.
  HoverHandler {
    id: btHover
    enabled: bt.plOnly
  }
  readonly property string catId: "cat:" + path
  readonly property string catSt: plOnly ? host.dlSt(catId) : ""
  // Both states ride one riser, so a running rollup keeps showing after
  // the pointer leaves (same rule as the album cards' controls).
  RiseIn {
    host: bt.host
    on: bt.plOnly && (btHover.hovered || bt.catSt !== "")
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 10
    height: 34
    // Same roll as the album cards: the strip and the live rollup button
    // are one pill that changes its contents, not two that blink.
    RollSwap {
      id: catSwap
      host: bt.host
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.verticalCenter: parent.verticalCenter
      live: bt.catSt !== ""
      liveColor: catBtn.fill
      liveBorder: catBtn.edge
      idleItem: Item {
        // Same pill as the album-card strip, one notch smaller: at the
        // card sizes the natural width overflows the 200px tile, so the
        // labels drop to 9px and the segment padding tightens to fit.
        id: catStrip
        width: catStripRow.implicitWidth
        height: 30
        // Hover swell, same wiring as the album cards' strip (see there
        // for why one handler and why PREVIEW overshoots the divider).
        HoverHandler {
          id: catStripHover
        }
        readonly property real dividerX: catStripRow.children[0].width
        readonly property real hoverX: catStripHover.point.position.x
        HoverSwell {
          z: 1    // above the Row, so the lit edge covers the divider
          width: catStrip.dividerX + btnBorderW
          height: catStrip.height
          radR: 0
          on: catStripHover.hovered && catStrip.hoverX <= catStrip.dividerX
        }
        HoverSwell {
          z: 1
          x: catStrip.dividerX
          width: catStrip.width - catStrip.dividerX
          height: catStrip.height
          radL: 0
          on: catStripHover.hovered && catStrip.hoverX > catStrip.dividerX
        }
        Row {
          id: catStripRow
          anchors.verticalCenter: parent.verticalCenter
          Item {
            implicitWidth: catStripPv.implicitWidth + 14
            implicitHeight: 30
            Row {
              id: catStripPv
              anchors.centerIn: parent
              spacing: 5
              Ico {
                name: "play"
                color: accent
                size: 10
                anchors.verticalCenter: parent.verticalCenter
              }
              Text {
                textFormat: Text.PlainText
                text: "PREVIEW"
                color: accent
                font.family: uiFont
                font.pixelSize: 9
                font.bold: true
                font.letterSpacing: btnTrack
                anchors.verticalCenter: parent.verticalCenter
              }
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                host.catPendingPv = bt.path
                waves.resolvePlaylistCategory(bt.path, bt.title)
              }
            }
          }
          Rectangle {
            width: btnBorderW
            height: 30
            color: accentDim
            anchors.verticalCenter: parent.verticalCenter
          }
          Item {
            implicitWidth: catStripDl.implicitWidth + 14
            implicitHeight: 30
            Row {
              id: catStripDl
              anchors.centerIn: parent
              spacing: 5
              Ico {
                name: "arrow-down"
                color: accent
                size: 11
                bold: 10
                anchors.verticalCenter: parent.verticalCenter
              }
              Text {
                textFormat: Text.PlainText
                text: "DOWNLOAD ALL"
                color: accent
                font.family: uiFont
                font.pixelSize: 9
                font.bold: true
                font.letterSpacing: btnTrack
                anchors.verticalCenter: parent.verticalCenter
              }
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                host.catPendingDl = bt.path
                waves.resolvePlaylistCategory(bt.path, bt.title)
              }
            }
          }
        }
      }
      liveItem: DownloadButton {
        id: catBtn
        host: bt.host
        bare: true
        mediaId: bt.catId
        chooserKind: "category"
        label: "Download all"
        // Retry after a failed rollup re-queues from the cached list.
        onTap: function () {
          waves.downloadPlaylistCategory(bt.path)
        }
      }
    }
    // The count badge deliberately overhangs the button's corner, so it
    // cannot ride inside the pill's clipping window. It sits alongside and
    // arrives with the button instead.
    FolderBadge {
      host: bt.host
      anchors.right: catSwap.right
      anchors.rightMargin: -8
      anchors.top: catSwap.top
      anchors.topMargin: -9
      folderId: bt.catId
      st: catBtn.st
      // Ride the swap AND keep the component's own reasons to hide: an
      // override replaces the whole binding, so `catSwap.inFrac` alone
      // pinned the badge opaque through its `gone` dismissal (a shrunken
      // ✓ parked on the corner for the life of the tile) and the plain
      // `opacity > 0.004` dropped the empty-value guard, showing a bare
      // pill with no digit for the whole folder-tree warm.
      opacity: catSwap.inFrac * (gone ? 0 : 1)
      visible: opacity > 0.004 && value !== ""
    }
  }
}

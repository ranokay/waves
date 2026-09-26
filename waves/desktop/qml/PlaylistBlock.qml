import QtQuick
import QtQuick.Layouts
import "primitives" as Primitives

// Playlist row + inline expand: the playlist counterpart of AlbumBlock,
// same interaction grammar (row click expands the track list in place,
// the title opens the dedicated page). Unlike an album a playlist
// mutates, so every expand refetches its rows instead of caching them
// for the session; video entries keep their kind so preview and
// download route as videos.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.expandMoveMs / host.expandedPlaylists / host.hoverPrefetch /
//   host.hoverPrefetchCancel / host.openPlaylistPage /
//   host.playlistTrackCache / host.rememberExpandReturn /
//   host.scrollCollapsedBack / host.scrollExpandedIntoView
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Column {
  id: pb
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property int btnPadH: 12   // label padding, left/right
  readonly property int btnPadV: 7   // label padding, top/bottom
  readonly property int btnRad: 8   // button corner radius
  readonly property real btnTrack: 0   // label letter-spacing
  readonly property color divider: "#22262d"
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color surface0: "#121418"   // topbar / statusbar / expand panel
  readonly property color surface2: "#191c22"   // hover / nested
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)

  property string plId: ""
  property string title: ""
  property string creator: ""
  property string art: ""
  property int trackCount: 0
  readonly property bool expanded: host.expandedPlaylists[plId] === true
  // sel maps ROW INDEX -> kind ("track"/"video") so Download selected
  // routes each pick to the right slot. Keyed by index, not by track id:
  // a playlist may legitimately list the same track twice, and an id key
  // would tie those rows to one checkbox (and leave allSelected forever
  // false). Same recycling rationale as AlbumBlock: expand state global,
  // selection per delegate.
  property var sel: ({})
  // Same as AlbumBlock.folding: true only while a press folds the panel
  // shut, so a recycled delegate blanks instead of folding.
  property bool folding: false
  onPlIdChanged: {
    sel = ({})
    folding = false
  }
  readonly property var trackList: host.playlistTrackCache[plId] || []
  // Row indices only mean something against the list they were picked
  // from, and a re-expand refetches (playlists mutate). A replaced list
  // must not point the old indices at other tracks, but wholesale
  // dropping the selection eats ticks made during the refetch window
  // (the stale rows stay on screen while the fetch runs), so remap by
  // track id instead: a tick survives if its track is still in the
  // list, and vanishes with the track if the playlist lost it.
  // Plain [] on purpose: a binding here would re-evaluate to the NEW
  // list before the handler below could read the old one.
  property var _selList: []
  onTrackListChanged: {
    var old = _selList, byId = {}, s = {}
    for (var i = 0; i < trackList.length; ++i)
      byId[trackList[i].id] = i
    for (var k in sel) {
      var t = old[k]
      if (t && byId[t.id] !== undefined)
        s[byId[t.id]] = sel[k]
    }
    sel = s
    _selList = trackList
  }
  readonly property int selCount: Object.keys(sel).length
  readonly property bool allSelected: trackList.length > 0 && selCount === trackList.length
  readonly property string subLabel: (trackCount > 0 ? trackCount + " tracks" : "Playlist") + (creator ? "  ·  " + creator : "")
  // Shrinks with the panel's last 6px, as on AlbumBlock above.
  spacing: Math.min(6, pbPanel.height)

  function toggle() {
    var e = Object.assign({}, host.expandedPlaylists)
    if (e[plId]) {
      delete e[plId]
      folding = true
    } else {
      e[plId] = true
      folding = false
      waves.loadPlaylistTracks(plId)
    }
    host.expandedPlaylists = e
    var key = plId
    if (e[plId])
      Qt.callLater(function () {
        if (pb.expanded)
          host.rememberExpandReturn(key, host.scrollExpandedIntoView(pb))
      })
    else
      host.scrollCollapsedBack(key, pb)
  }
  function setSel(row, kind, v) {
    var s = Object.assign({}, sel)
    if (v)
      s[row] = kind
    else
      delete s[row]
    sel = s
  }
  function toggleAll() {
    if (allSelected) {
      sel = ({})
    } else {
      var s = {}
      for (var i = 0; i < trackList.length; ++i)
        s[i] = trackList[i].kind
      sel = s
    }
  }
  function downloadSelected() {
    for (var k in sel) {
      var row = trackList[k]
      if (!row)
        continue
      if (sel[k] === "video")
        waves.downloadVideo(row.id)
      else
        waves.downloadTrack(row.id)
    }
  }

  // Row
  Rectangle {
    width: parent.width
    height: 64
    radius: 10
    color: pbRowMa.containsMouse ? surface2 : surface
    border.color: expanded ? outline : border1
    RowLayout {
      anchors.fill: parent
      anchors.leftMargin: 12
      anchors.rightMargin: 14
      spacing: 12
      Text {
        text: "›"
        rotation: expanded ? 90 : 0
        color: expanded ? accent : textDim
        font.pixelSize: 16
        Layout.preferredWidth: 12
        horizontalAlignment: Text.AlignHCenter
        Behavior on rotation {
          NumberAnimation {
            duration: 160
            easing.type: Easing.OutCubic
          }
        }
      }
      Art {
        host: pb.host
        width: 46
        height: 46
        hoverFx: true
        fxKind: "playlist"
        fxId: plId
        url: art
      }
      ColumnLayout {
        Layout.fillWidth: true
        spacing: 2
        Text {
          textFormat: Text.PlainText
          text: title
          color: pbRowTitleMa.containsMouse ? "#ffffff" : textHi
          font.pixelSize: 14
          font.bold: true
          elide: Text.ElideRight
          Layout.fillWidth: true
          // Title -> the playlist's dedicated page (row click still expands)
          MouseArea {
            id: pbRowTitleMa
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: Math.min(parent.width, parent.implicitWidth)
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: host.openPlaylistPage(plId, title, art)
            // Resting on the link: have the page ready (see hoverPrefetch).
            readonly property var prefetchCard: ({
                kind: "playlist",
                id: pb.plId,
                art: pb.art
              })
            onContainsMouseChanged: containsMouse ? host.hoverPrefetch(prefetchCard) : host.hoverPrefetchCancel(prefetchCard)
          }
        }
        Text {
          textFormat: Text.PlainText
          text: pb.subLabel
          color: textLo
          font.pixelSize: 12
          elide: Text.ElideRight
          Layout.fillWidth: true
        }
      }
      DownloadButton {
        host: pb.host
        Layout.alignment: Qt.AlignVCenter
        mediaId: plId
        chooserKind: "playlist"
        collectionCheck: true
        label: "Download playlist"
        onTap: function () {
          waves.downloadPlaylist(plId)
        }
      }
    }
    MouseArea {
      id: pbRowMa
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      z: -1
      onClicked: toggle()
    }
  }

  // Expanded rich panel
  Rectangle {
    id: pbPanel
    width: parent.width
    // Folds shut on the same clock as the scroll back, for the reason
    // spelled out on the album panel above.
    visible: expanded || pb.folding
    height: expanded ? pbExpandedCol.height + 24 : 0
    opacity: expanded ? 1 : 0
    enabled: expanded
    onHeightChanged: if (!expanded && height <= 0.5)
      pb.folding = false
    Behavior on height {
      NumberAnimation {
        duration: host.expandMoveMs
        easing.type: Easing.OutCubic
      }
    }
    Behavior on opacity {
      NumberAnimation {
        duration: host.expandMoveMs
        easing.type: Easing.OutCubic
      }
    }
    color: surface0
    border.color: border1
    radius: 10
    Column {
      id: pbExpandedCol
      x: 16
      y: 12
      width: parent.width - 32
      spacing: 12
      Row {
        width: parent.width
        spacing: 16
        Art {
          host: pb.host
          width: 116
          height: 116
          hoverFx: true
          fxKind: "playlist"
          fxId: plId
          url: art
        }
        Column {
          width: parent.width - 132
          spacing: 6
          Text {
            text: "PLAYLIST"
            color: textDim
            font.pixelSize: 11
          }
          Text {
            textFormat: Text.PlainText
            text: title
            color: pbPanelTitleMa.containsMouse ? "#ffffff" : textHi
            font.pixelSize: 21
            font.bold: true
            width: parent.width
            elide: Text.ElideRight
            MouseArea {
              id: pbPanelTitleMa
              anchors.left: parent.left
              anchors.top: parent.top
              anchors.bottom: parent.bottom
              width: Math.min(parent.width, parent.implicitWidth)
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: host.openPlaylistPage(plId, title, art)
            }
          }
          Text {
            textFormat: Text.PlainText
            text: pb.subLabel
            color: textLo
            font.pixelSize: 14
            width: parent.width
            elide: Text.ElideRight
          }
          Row {
            spacing: 10
            topPadding: 6
            DownloadButton {
              host: pb.host
              mediaId: plId
              label: "Download playlist"
              chooserKind: "playlist"
              collectionCheck: true
              onTap: function () {
                waves.downloadPlaylist(plId)
              }
            }
            Text {
              text: "Copy link"
              color: textLo
              font.pixelSize: 12
              anchors.verticalCenter: parent.verticalCenter
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: waves.copyShareUrl("playlist", plId)
              }
            }
          }
        }
      }
      Text {
        visible: !host.playlistTrackCache[plId]
        text: "Loading tracks…"
        color: textLo
        font.pixelSize: 13
      }
      Column {
        width: parent.width
        spacing: 0
        // Select-all header
        RowLayout {
          visible: pb.trackList.length > 0
          width: parent.width
          height: 40
          spacing: 12
          Check {
            Layout.alignment: Qt.AlignVCenter
            checked: pb.allSelected
            onToggled: pb.toggleAll()
          }
          Text {
            text: "Select all"
            color: textLo
            font.pixelSize: 13
          }
          Text {
            textFormat: Text.PlainText
            text: "· " + pb.selCount + " of " + pb.trackList.length + " selected"
            color: textDim
            font.pixelSize: 12
          }
          Item {
            Layout.fillWidth: true
          }
          Rectangle {
            Layout.alignment: Qt.AlignVCenter
            opacity: pb.selCount > 0 ? 1 : 0.4
            // Sized like DownloadButton so it matches DOWNLOAD PLAYLIST above.
            radius: btnRad
            color: accentCont
            border.color: accentDim
            border.width: 1
            implicitHeight: pbDsRow.implicitHeight + btnPadV * 2
            implicitWidth: pbDsRow.implicitWidth + btnPadH * 2
            Row {
              id: pbDsRow
              anchors.centerIn: parent
              spacing: 7
              Ico {
                name: "arrow-down"
                color: accent
                size: 14
                bold: 10
                anchors.verticalCenter: parent.verticalCenter
              }
              Text {
                text: "DOWNLOAD SELECTED"
                color: accent
                font.pixelSize: 11
                font.family: uiFont
                font.bold: true
                font.letterSpacing: btnTrack
                anchors.verticalCenter: parent.verticalCenter
              }
            }
            MouseArea {
              anchors.fill: parent
              enabled: pb.selCount > 0
              cursorShape: pb.selCount > 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
              onClicked: pb.downloadSelected()
            }
          }
        }
        // Tracks (playlist order; a video entry previews and
        // downloads as a video)
        Repeater {
          model: pb.trackList
          delegate: Rectangle {
            required property var modelData
            required property int index
            width: parent.width
            height: 40
            color: "transparent"
            Rectangle {
              anchors.bottom: parent.bottom
              width: parent.width
              height: 1
              color: divider
            }
            RowLayout {
              anchors.fill: parent
              anchors.leftMargin: 4
              anchors.rightMargin: 4
              spacing: 12
              Check {
                Layout.alignment: Qt.AlignVCenter
                checked: pb.sel[index] !== undefined
                onToggled: pb.setSel(index, modelData.kind, pb.sel[index] === undefined)
              }
              Text {
                textFormat: Text.PlainText
                text: modelData.num
                color: textDim
                font.family: mono
                font.pixelSize: 15
                font.bold: true
                Layout.preferredWidth: 24
                Layout.leftMargin: -4
                horizontalAlignment: Text.AlignLeft
              }
              TrackPreview {
                host: pb.host
                kind: modelData.kind
                pid: modelData.id
                Layout.alignment: Qt.AlignVCenter
              }
              Text {
                textFormat: Text.PlainText
                text: modelData.title
                color: textHi
                font.pixelSize: 13
                elide: Text.ElideRight
                Layout.fillWidth: true
              }
              Text {
                textFormat: Text.PlainText
                text: modelData.artist
                color: textLo
                font.pixelSize: 12
                elide: Text.ElideRight
                Layout.maximumWidth: 220
              }
              PopMeter {
                host: pb.host
                value: modelData.popularity
                showNum: false
              }
              Text {
                textFormat: Text.PlainText
                text: modelData.duration
                color: textLo
                font.family: mono
                font.pixelSize: 12
                Layout.preferredWidth: 42
              }
              DownIcon {
                host: pb.host
                mediaId: modelData.id
                // A playlist row carries its own artist but
                // names no release, so the match keeps its
                // hedge (gold). Never for a video: the
                // library scan only ever holds audio.
                libTrack: modelData.kind === "video" ? null : ({
                    artist: modelData.artist,
                    title: modelData.title
                  })
                onTap: function () {
                  if (modelData.kind === "video")
                    waves.downloadVideo(modelData.id)
                  else
                    waves.downloadTrack(modelData.id)
                }
              }
            }
          }
        }
      }
    }
  }
}

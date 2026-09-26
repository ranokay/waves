import QtQuick
import QtQuick.Layouts
import "primitives" as Primitives

// Album row + inline expand. Local expanded state so it works in both the
// search results and inside an artist page.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.artistsById / host.expandMoveMs / host.expandedAlbums /
//   host.hoverPrefetch / host.hoverPrefetchCancel / host.isNewRelease /
//   host.onAlbumPage / host.openAlbumPage / host.qualMixList /
//   host.rememberExpandReturn / host.scrollCollapsedBack /
//   host.scrollExpandedIntoView / host.trackCache
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Column {
  id: ab
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property int btnPadH: 12             // label padding, left/right
  readonly property int btnPadV: 7              // label padding, top/bottom
  readonly property int btnRad: 8              // button corner radius
  readonly property real btnTrack: 0              // label letter-spacing
  readonly property color divider: "#22262d"
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color surface0: "#121418"   // topbar / statusbar / expand panel
  readonly property color surface2: "#191c22"   // hover / nested
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)

  property string albumId: ""
  property string title: ""
  property string artistName: ""
  property string artistId: ""
  property string art: ""
  property string year: ""
  property string releaseDate: ""
  property string listedDate: ""   // the day a reissue was really listed, "" otherwise: shown over releaseDate
  property int trackCount: 0
  property int durationSec: 0      // raw seconds, the presence matcher's duration witness
  property string quality: ""
  property int popularity: 0
  // Expand state is held globally (keyed by album id) so it survives
  // ListView delegate recycling in the virtualised My Music lists.
  readonly property bool expanded: host.expandedAlbums[albumId] === true
  property var sel: ({})
  // sel holds raw track ids, so a recycled delegate rebinding to a new
  // album (LibList sets reuseItems) would download the PREVIOUS album's
  // selection; expanded/trackList live in global maps for that reason,
  // the per-delegate selection resets instead.
  // True only while a press is folding this row's panel shut (the panel
  // below explains why it has to outlive the press). Cleared on recycle:
  // a delegate rebinding to another album must not carry a fold that
  // belonged to the row it just left.
  property bool folding: false
  onAlbumIdChanged: {
    sel = ({})
    folding = false
  }
  readonly property var trackList: host.trackCache[albumId] || []
  // Tier split once the tracks are known (expand fetches them), flips
  // the quality badge to MIXED when the album spans tiers.
  readonly property var qualMix: host.qualMixList(trackList)
  readonly property int selCount: Object.keys(sel).length
  readonly property bool allSelected: trackList.length > 0 && selCount === trackList.length
  // The gap under the row belongs to the panel, so it has to go with it:
  // a fixed 6 stayed until the folded panel left the layout and then
  // vanished in one frame, a small extra collapse after the motion had
  // already ended. Shrinking it over the panel's last 6px keeps the
  // whole close continuous.
  spacing: Math.min(6, abPanel.height)
  // The artists this block should link: the side-map array when the
  // payload carried one, else a single entry from artistName/artistId
  // (same fallback as cardLeadArtists, so search albums always show a
  // clickable artist like the track rows do).
  readonly property var leadArtists: {
    var a = host.artistsById[albumId] || []
    if (a.length > 0)
      return a
    return artistName !== "" ? [
      {
        id: artistId,
        name: artistName
      }
    ] : []
  }

  function toggle() {
    var e = Object.assign({}, host.expandedAlbums)
    if (e[albumId]) {
      delete e[albumId]
      folding = true
    } else {
      e[albumId] = true
      folding = false
      if (!host.trackCache[albumId])
        waves.loadAlbumTracks(albumId)
    }
    host.expandedAlbums = e
    // After the panel exists (next event loop turn, so its height is
    // laid out), bring the row up to the expand anchor line, keeping
    // the spot the view left so the collapse can return to it.
    var key = albumId
    if (e[albumId])
      Qt.callLater(function () {
        if (ab.expanded)
          host.rememberExpandReturn(key, host.scrollExpandedIntoView(ab))
      })
    else
      host.scrollCollapsedBack(key, ab)
  }
  function setSel(tid, v) {
    var s = Object.assign({}, sel)
    if (v)
      s[tid] = true
    else
      delete s[tid]
    sel = s
  }
  function toggleAll() {
    if (allSelected) {
      sel = ({})
    } else {
      var s = {}
      for (var i = 0; i < trackList.length; ++i)
        s[trackList[i].id] = true
      sel = s
    }
  }
  function downloadSelected() {
    for (var k in sel)
      waves.downloadTrack(k)
  }

  // Row
  Rectangle {
    width: parent.width
    height: 64
    radius: 10
    color: rowMa.containsMouse ? surface2 : surface
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
        host: ab.host
        width: 46
        height: 46
        hoverFx: true
        fxKind: "album"
        fxId: albumId
        url: art
      }
      ColumnLayout {
        Layout.fillWidth: true
        spacing: 2
        // Title with the presence pill floating right beside the
        // rendered text (static, quality told by its colour class).
        // The pill lives INSIDE the full-width Text so the title
        // keeps its layout size and elides only for real overflow.
        Text {
          id: abRowTitle
          textFormat: Text.PlainText
          text: title
          color: abRowTitleMa.containsMouse ? "#ffffff" : textHi
          font.pixelSize: 14
          font.bold: true
          elide: Text.ElideRight
          Layout.fillWidth: true
          rightPadding: (abRowPill.visible ? abRowPill.width + 8 : 0) + (abRowNew.visible ? abRowNew.width + (abRowPill.visible ? 6 : 8) : 0)
          // Title -> the album's dedicated page (row click still expands)
          MouseArea {
            id: abRowTitleMa
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: Math.min(parent.width, parent.implicitWidth)
            enabled: !host.onAlbumPage(albumId)
            hoverEnabled: enabled
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: host.openAlbumPage(albumId, "", title, art)
            // Resting on the link: have the page ready (see hoverPrefetch).
            readonly property var prefetchCard: ({
                kind: "album",
                id: ab.albumId,
                art: ab.art
              })
            onContainsMouseChanged: containsMouse ? host.hoverPrefetch(prefetchCard) : host.hoverPrefetchCancel(prefetchCard)
          }
          AlbumPresencePill {
            id: abRowPill
            host: ab.host
            anchors.verticalCenter: parent.verticalCenter
            x: Math.min(abRowTitle.contentWidth + 8, abRowTitle.width - width - (abRowNew.visible ? abRowNew.width + 6 : 0))
            album: ({
                artist: ab.artistName,
                title: ab.title,
                year: ab.year,
                tracks: ab.trackCount,
                duration_sec: ab.durationSec
              })
          }
          // Tested on the date the row shows (a reissue's listed
          // day over TIDAL's original), so the two never disagree.
          NewTag {
            id: abRowNew
            host: ab.host
            visible: host.isNewRelease(ab.listedDate !== "" ? ab.listedDate : ab.releaseDate)
            settled: abDl.st === "done"
            anchors.verticalCenter: parent.verticalCenter
            x: abRowPill.visible ? abRowPill.x + abRowPill.width + 6 : Math.min(abRowTitle.contentWidth + 8, abRowTitle.width - width)
          }
        }
        ArtistLinks {
          host: ab.host
          Layout.fillWidth: true
          artists: ab.leadArtists
          suffix: (listedDate !== "" ? listedDate : releaseDate !== "" ? releaseDate : year) + (trackCount > 0 ? " · " + trackCount + " trks" : "")
        }
      }
      PopMeter {
        host: ab.host
        value: popularity
        Layout.alignment: Qt.AlignVCenter
      }
      // Badge slot like the track rows: sized to the widest real badge,
      // badge right-aligned, so the popularity column doesn't stagger
      // with badge width. A wider MIXED tag gets its natural width.
      // 14px of slack on top, the room the badge grows into for its
      // caret when hovered (see TrackRow's slot).
      Item {
        QualTag {
          id: abQtMetric
          host: ab.host
          visible: false
          q: "LOSSLESS"
        }
        Layout.preferredWidth: Math.max(abQtMetric.implicitWidth, abQt.implicitWidth) + 14
        Layout.preferredHeight: 22
        Layout.alignment: Qt.AlignVCenter
        QualPick {
          id: abQt
          host: ab.host
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          // ab.albumId, qualified: a bare albumId here is the
          // picker's own (empty) inheritance property.
          mediaId: ab.albumId
          catalog: ab.quality
          mix: ab.qualMix
        }
      }
      DownloadButton {
        id: abDl
        host: ab.host
        Layout.alignment: Qt.AlignVCenter
        mediaId: albumId
        collectionCheck: true
        label: "Download album"
        chooserKind: "album"
        libAlbum: ({
            artist: ab.artistName,
            title: ab.title,
            year: ab.year,
            tracks: ab.trackCount,
            duration_sec: ab.durationSec
          })
        onTap: function () {
          waves.downloadAlbum(albumId)
        }
      }
    }
    MouseArea {
      id: rowMa
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      z: -1
      onClicked: toggle()
      // Resting on the row: have its tracks fetched before the
      // click expands it (see hoverPrefetch), so the panel opens on
      // its rows instead of "Loading tracks…" and a pop-in. Only
      // while collapsed with nothing cached; the key is empty
      // otherwise and the arm is a no-op.
      readonly property var prefetchCard: ({
          kind: "album_tracks",
          id: ab.albumId
        })
      onContainsMouseChanged: containsMouse && !ab.expanded ? host.hoverPrefetch(prefetchCard) : host.hoverPrefetchCancel(prefetchCard)
    }
  }

  // Expanded rich panel
  Rectangle {
    id: abPanel
    width: parent.width
    // The panel stays on screen while it folds shut. A Column drops an
    // invisible child from its layout outright, so `visible: expanded`
    // closed the whole gap in one frame while the view was still
    // gliding back to where the expand had left it: the page snapped
    // and the scroll trailed after it. Folding on the same clock as
    // that scroll makes the two one motion. `folding` marks a real
    // collapse (the press that closed the row sets it, the fold
    // reaching zero clears it), so a recycled delegate rebinding to a
    // collapsed album still blanks at once.
    visible: expanded || ab.folding
    height: expanded ? expandedCol.height + 24 : 0
    // Fades with the fold: the column inside keeps its full height
    // while the panel shrinks, and an unclipped panel would otherwise
    // draw the tracks over the rows closing in below them.
    opacity: expanded ? 1 : 0
    // A panel on its way out takes no more presses: the band still
    // closing under the cursor must not fire a download.
    enabled: expanded
    onHeightChanged: if (!expanded && height <= 0.5)
      ab.folding = false
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
      id: expandedCol
      x: 16
      y: 12
      width: parent.width - 32
      spacing: 12
      Row {
        width: parent.width
        spacing: 16
        Art {
          host: ab.host
          width: 116
          height: 116
          hoverFx: true
          fxKind: "album"
          fxId: albumId
          url: art
        }
        Column {
          width: parent.width - 132 - abPanelMeta.width - 16
          spacing: 6
          Text {
            text: "ALBUM"
            color: textDim
            font.pixelSize: 11
          }
          Text {
            textFormat: Text.PlainText
            text: title
            color: abPanelTitleMa.containsMouse ? "#ffffff" : textHi
            font.pixelSize: 21
            font.bold: true
            width: parent.width
            elide: Text.ElideRight
            MouseArea {
              id: abPanelTitleMa
              anchors.left: parent.left
              anchors.top: parent.top
              anchors.bottom: parent.bottom
              width: Math.min(parent.width, parent.implicitWidth)
              enabled: !host.onAlbumPage(albumId)
              hoverEnabled: enabled
              cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
              onClicked: host.openAlbumPage(albumId, "", title, art)
            }
          }
          ArtistLinks {
            host: ab.host
            width: parent.width
            px: 14
            artists: ab.leadArtists
            suffix: (listedDate !== "" ? listedDate : releaseDate !== "" ? releaseDate : year) + (trackCount > 0 ? " · " + trackCount + " tracks" : "")
          }
          Row {
            spacing: 10
            topPadding: 6
            // With the merge preference on the backend runs the
            // best-of-both scan behind this same button; no
            // separate action.
            DownloadButton {
              host: ab.host
              mediaId: albumId
              label: "Download album"
              chooserKind: "album"
              collectionIds: ab.trackList.length > 0 ? ab.trackList.map(function (t) {
                return t.id
              }) : []
              libAlbum: ({
                  artist: ab.artistName,
                  title: ab.title,
                  year: ab.year,
                  tracks: ab.trackCount,
                  duration_sec: ab.durationSec
                })
              onTap: function () {
                waves.downloadAlbum(albumId)
              }
            }
            StandalonePair {
              mediaId: albumId
              anchors.verticalCenter: parent.verticalCenter
            }
            Text {
              text: "Copy link"
              color: textLo
              font.pixelSize: 12
              anchors.verticalCenter: parent.verticalCenter
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: waves.copyShareUrl("album", albumId)
              }
            }
          }
        }
        // Quality + popularity stacked top-right, out of the action row.
        Column {
          id: abPanelMeta
          spacing: 8
          topPadding: 4
          QualPick {
            host: ab.host
            anchors.right: parent.right
            mediaId: ab.albumId
            catalog: ab.quality
            mix: ab.qualMix
          }
          PopMeter {
            host: ab.host
            anchors.right: parent.right
            value: popularity
          }
        }
      }
      Text {
        visible: !host.trackCache[albumId]
        text: "Loading tracks…"
        color: textLo
        font.pixelSize: 13
      }
      Column {
        width: parent.width
        spacing: 0
        // Select-all header
        RowLayout {
          visible: ab.trackList.length > 0
          width: parent.width
          height: 40
          spacing: 12
          Check {
            Layout.alignment: Qt.AlignVCenter
            checked: ab.allSelected
            onToggled: ab.toggleAll()
          }
          Text {
            text: "Select all"
            color: textLo
            font.pixelSize: 13
          }
          Text {
            textFormat: Text.PlainText
            text: "· " + ab.selCount + " of " + ab.trackList.length + " selected"
            color: textDim
            font.pixelSize: 12
          }
          Item {
            Layout.fillWidth: true
          }
          Rectangle {
            Layout.alignment: Qt.AlignVCenter
            opacity: ab.selCount > 0 ? 1 : 0.4
            // Sized like DownloadButton so it matches DOWNLOAD ALBUM above.
            radius: btnRad
            color: accentCont
            border.color: accentDim
            border.width: 1
            implicitHeight: dsRow.implicitHeight + btnPadV * 2
            implicitWidth: dsRow.implicitWidth + btnPadH * 2
            Row {
              id: dsRow
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
              enabled: ab.selCount > 0
              cursorShape: ab.selCount > 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
              onClicked: ab.downloadSelected()
            }
          }
        }
        // Tracks
        Repeater {
          model: ab.trackList
          delegate: Rectangle {
            required property var modelData
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
                checked: ab.sel[modelData.id] === true
                onToggled: ab.setSel(modelData.id, !(ab.sel[modelData.id] === true))
              }
              Text {
                textFormat: Text.PlainText
                text: modelData.num
                color: textDim
                font.family: mono
                font.pixelSize: 15
                font.bold: true
                Layout.preferredWidth: 16
                Layout.leftMargin: -4
                horizontalAlignment: Text.AlignLeft
              }
              TrackPreview {
                host: ab.host
                kind: "track"
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
              PopMeter {
                host: ab.host
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
                host: ab.host
                mediaId: modelData.id
                // The panel knows the release these rows
                // belong to, so a match here can be PROVEN
                // (green) rather than hedged by title alone.
                libTrack: ({
                    artist: ab.artistName,
                    title: modelData.title,
                    album: ab.title,
                    year: ab.year
                  })
                onTap: function () {
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

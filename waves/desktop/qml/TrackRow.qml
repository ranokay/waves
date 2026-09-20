import QtQuick
import QtQuick.Layouts

// Full track row (search results + artist top tracks)
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.artistsById / host.hoverPrefetch / host.hoverPrefetchCancel /
//   host.isNewRelease / host.onAlbumPage / host.openAlbumPage /
//   host.openVideo
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: trow
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color surface2: "#191c22"   // hover / nested
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  property string tId: ""
  property string kind: "track"   // "video" rows play/download as videos
  property string title: ""
  property string artistName: ""
  property string artistId: ""
  property string album: ""
  property string art: ""
  property string year: ""
  property string date: ""
  property string duration: ""
  property int durationSec: 0      // raw seconds, the presence matcher's duration witness
  property string quality: ""
  property int popularity: 0
  property bool hi: false          // "you came here for this track" marker
  property int num: 0              // track # (album position, or playlist order); 0 hides
  property string albumId: ""      // set -> the title links to the album page
  // A file on disk (the Library section's rows, ADR 0007): the row's
  // provider actions have no catalog item to act on, so they stand
  // down, and the row's own action is revealing its folder instead.
  property bool local: false
  // The provider the file was saved from, "" when untagged: the badge
  // an untagged row must NOT grow (ADR 0007), plus the descriptor mark
  // that provider's badge shows. Only local rows read them.
  property string provider: ""
  property string providerLogo: ""
  // The album folder on disk: where a local row's reveal lands.
  property string folderPath: ""
  readonly property bool revealable: local && folderPath !== ""
  height: 62
  color: "transparent"
  // A pointer that settles on a row is often about to open the album
  // (the row, the title and the album link all go there). Longer dwell
  // than a card: a row is also where a pointer parks while reading.
  // A HoverHandler, not the row's MouseArea: the thumb, title and
  // buttons stacked above it each take hover, so containsMouse would
  // restart the dwell at every internal edge. No art is passed: a row's
  // cover is the small size, and the page hero asks for the card size,
  // so warming it here would pin a pixmap nobody asks for (the hero is
  // warmed properly when the prefetch lands).
  readonly property var prefetchCard: ({
      kind: "album",
      id: trow.albumId,
      art: ""
    })
  HoverHandler {
    enabled: !trow.local && trow.kind !== "video" && trow.albumId !== ""
    onHoveredChanged: hovered ? host.hoverPrefetch(trow.prefetchCard, 450) : host.hoverPrefetchCancel(trow.prefetchCard)
  }
  // Framed card row:
  // same surface/border/hover language as the album section, and the
  // same DownloadButton as everywhere else, labeled for the track.
  Rectangle {
    anchors.fill: parent
    anchors.topMargin: 3
    anchors.bottomMargin: 3
    radius: 10
    color: trowMa.containsMouse ? surface2 : surface
    border.color: border1
    // Blank space anywhere on the row navigates like the title does
    // (the track's album page, or the video player): most of the row
    // is clickable, while the artist/album links, meters and buttons
    // stacked above still take their own clicks first.
    MouseArea {
      id: trowMa
      anchors.fill: parent
      hoverEnabled: true
      readonly property bool linkable: trow.kind === "video" || (trow.albumId !== "" && !host.onAlbumPage(trow.albumId))
      acceptedButtons: (trow.revealable || (!trow.local && linkable)) ? Qt.LeftButton : Qt.NoButton
      cursorShape: (trow.revealable || (!trow.local && linkable)) ? Qt.PointingHandCursor : Qt.ArrowCursor
      // A local row reveals the file's album folder in the file
      // manager: the row's own copy IS the action on disk.
      onClicked: trow.revealable ? waves.revealLibraryAlbum(trow.folderPath) : trow.kind === "video" ? host.openVideo(trow.tId, trow.title, trow.artistName) : host.openAlbumPage(trow.albumId, trow.tId, trow.album, trow.art)
    }
    // Highlight = the "Fade" treatment: a green tint strongest at the
    // left, gone before the metadata columns so numbers and badges sit
    // on clean background.
    Rectangle {
      visible: hi
      anchors.fill: parent
      radius: 10
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop {
          position: 0.0
          color: "#e006210f"
        }
        GradientStop {
          position: 0.45
          color: "#7006210f"
        }
        GradientStop {
          position: 1.0
          color: "#0006210f"
        }
      }
    }
    RowLayout {
      anchors.fill: parent
      anchors.leftMargin: 12
      anchors.rightMargin: 12
      spacing: 12
      Text {
        textFormat: Text.PlainText
        visible: num > 0
        text: num + "."
        // textHi to match the title's resting colour (set to the same
        // value, not bound to the title, which whitens on hover).
        color: textHi
        font.family: mono
        font.pixelSize: 12
        horizontalAlignment: Text.AlignRight
        Layout.preferredWidth: 24
        Layout.alignment: Qt.AlignVCenter
      }
      Item {
        // Video rows get a 16:9 thumb, the shape alone says "video".
        Layout.preferredWidth: trow.kind === "video" ? 78 : 44
        Layout.preferredHeight: 44
        Layout.alignment: Qt.AlignVCenter
        // A local file has nothing to preview: the cover, not the
        // disc with a play glyph, is the honest face.
        PreviewArt {
          host: trow.host
          visible: trow.kind !== "video" && !trow.local
          anchors.fill: parent
          kind: "track"
          pid: tId
          url: art
        }
        Art {
          host: trow.host
          visible: trow.kind === "video" || trow.local
          anchors.fill: parent
          url: art
        }
        PlayBadge {
          visible: trow.kind === "video"
          lit: thumbMa.containsMouse
          radius: 0
        }
        MouseArea {
          id: thumbMa
          anchors.fill: parent
          enabled: trow.kind === "video"
          hoverEnabled: enabled
          cursorShape: Qt.PointingHandCursor
          onClicked: host.openVideo(trow.tId, trow.title, trow.artistName)
        }
      }
      ColumnLayout {
        Layout.fillWidth: true
        spacing: 1
        Text {
          id: trTitle
          textFormat: Text.PlainText
          text: title
          color: trTitleMa.containsMouse ? "#ffffff" : textHi
          // A step above the 12px subtitle in both size and weight
          // so the title leads the row (the green artist link used
          // to outshine it).
          font.pixelSize: 14
          font.weight: Font.Medium
          elide: Text.ElideRight
          Layout.fillWidth: true
          // The presence pill floats beside the rendered text,
          // inside the full-width Text, exactly like the album
          // row's pill: the title keeps its layout size and
          // elides only for real overflow.
          rightPadding: (trPill.visible ? trPill.width + 8 : 0) + (trNew.visible ? trNew.width + (trPill.visible ? 6 : 8) : 0)
          // Title -> the track's album page (highlighting this track);
          // for a video row it opens the in-app video player instead.
          MouseArea {
            id: trTitleMa
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: Math.min(parent.width, parent.implicitWidth)
            enabled: trow.revealable || trow.kind === "video" || (albumId !== "" && !host.onAlbumPage(albumId))
            hoverEnabled: enabled
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: trow.revealable ? waves.revealLibraryAlbum(trow.folderPath) : trow.kind === "video" ? host.openVideo(trow.tId, trow.title, trow.artistName) : host.openAlbumPage(albumId, tId, trow.album, trow.art)
          }
          // Declared after the title's MouseArea so the pill sits
          // on top of it and takes its own click (reveal folder).
          // A library file needs no "in your library" pill: the
          // section it sits in already says it.
          TrackPresencePill {
            id: trPill
            host: trow.host
            visible: !trow.local && !!(presence && presence.present)
            anchors.verticalCenter: parent.verticalCenter
            x: Math.min(trTitle.contentWidth + 8, trTitle.width - width - (trNew.visible ? trNew.width + 6 : 0))
            track: trow.kind === "video" ? null : ({
                artist: trow.artistName,
                title: trow.title,
                album: trow.album,
                year: trow.year,
                duration_sec: trow.durationSec
              })
          }
          // On the album's own page too: each row goes steady on
          // its own as that track lands, which the header alone
          // cannot say.
          NewTag {
            id: trNew
            host: trow.host
            visible: trow.kind !== "video" && host.isNewRelease(trow.date)
            settled: trDl.st === "done"
            anchors.verticalCenter: parent.verticalCenter
            x: trPill.visible ? trPill.x + trPill.width + 6 : Math.min(trTitle.contentWidth + 8, trTitle.width - width)
          }
        }
        ArtistLinks {
          host: trow.host
          Layout.fillWidth: true
          artists: trow.local ? (trow.artistName !== "" ? [
              {
                id: "",
                name: trow.artistName
              }
            ] : []) : (host.artistsById[tId] || [])
          suffix: album
          albumId: trow.albumId
        }
      }
      PopMeter {
        host: trow.host
        value: popularity
        Layout.alignment: Qt.AlignVCenter
      }
      Text {
        textFormat: Text.PlainText
        text: date !== "" ? date : year
        color: textLo
        font.family: mono
        font.pixelSize: 12
        Layout.preferredWidth: 84
        Layout.alignment: Qt.AlignVCenter
      }
      Text {
        textFormat: Text.PlainText
        text: duration
        color: textLo
        font.family: mono
        font.pixelSize: 12
        Layout.preferredWidth: 40
        Layout.alignment: Qt.AlignVCenter
      }
      // Fixed-width slot, badge anchored right so it hugs the button,
      // short badges (HI-RES) leave the slack on their left, not as a
      // hole between badge and button. Sized to the widest real badge
      // (LOSSLESS 16/44.1) via a hidden metric, no padded guess.
      // 14px of slack on top: the badge grows leftwards by that much
      // to admit its caret when hovered, without moving the row.
      Item {
        QualTag {
          id: qtMetric
          host: trow.host
          visible: false
          q: "LOSSLESS"
        }
        // A local row's slot holds only the provenance badge (or
        // nothing): its quality is a file fact, not a catalog
        // pick, and an untagged file carries no provider to show.
        Layout.preferredWidth: trow.local ? 40 : qtMetric.implicitWidth + 14
        Layout.preferredHeight: trow.local ? 24 : 22
        Layout.alignment: Qt.AlignVCenter
        ProviderBadge {
          objectName: "trackProviderBadge"
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          // The mark gates the badge: a namespace no registered
          // provider claims has no logo (the bridge says so),
          // and the badge must not fall back to another
          // provider's mark for it.
          visible: trow.local && trow.providerLogo !== ""
          descriptor: ({
              id: trow.provider,
              logo: trow.providerLogo
            })
        }
        QualPick {
          host: trow.host
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          visible: !trow.local
          mediaId: trow.tId
          albumId: trow.albumId
          catalog: trow.quality
          pickable: trow.kind !== "video"
        }
      }
      DownloadButton {
        id: trDl
        host: trow.host
        // A file already on disk has nothing to download.
        visible: !trow.local
        Layout.alignment: Qt.AlignVCenter
        mediaId: tId
        ownedCheck: true
        chooserKind: trow.kind === "video" ? "video" : "track"
        label: trow.kind === "video" ? "Download video" : "Download track"
        // The same identity the pill beside the title resolves, so
        // the row says one thing in two places: the pill answers at
        // a glance, the button answers what a click will do. Videos
        // pass null, the scan holds no video.
        libTrack: trow.kind === "video" ? null : ({
            artist: trow.artistName,
            title: trow.title,
            album: trow.album,
            year: trow.year,
            duration_sec: trow.durationSec
          })
        onTap: function () {
          trow.kind === "video" ? waves.downloadVideo(tId) : waves.downloadTrack(tId)
        }
      }
      // Per-track standalone pair beside the track's split button:
      // always visible, so hovering never reflows the row. Videos
      // have no standalone lyrics/art, and a local file has no
      // catalog item to fetch them for.
      StandalonePair {
        Layout.alignment: Qt.AlignVCenter
        mediaId: tId
        compact: true
        visible: trow.kind !== "video" && !trow.local
      }
    }
  }
}

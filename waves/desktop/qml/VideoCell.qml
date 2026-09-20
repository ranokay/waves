import QtQuick

// One art-first video result cell: the 16:9 thumbnail carrying the quality
// spec on its corner, then the title, artist and release date baseline-
// aligned below, and the download button centred on the text block. The
// search VIDEOS grid and the artist page's VIDEOS section are the same
// cell at whatever width their grid hands it.
// 'host' is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load. The cell reads through it:
//   host.qualSpec(kind)  the tier's display spec for the video badge
//   host.artistsById  artistId -> name, for the credit line
// and the same object is handed to BigVideoThumb, ArtistLinks and the
// DownloadButton, which read their own contracts from it.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Column {
  id: vcell
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"
  property string vid: ""
  property string vcTitle: ""
  property string vcArtist: ""
  property string artUrl: ""
  property string artBigUrl: ""
  property string vcDuration: ""
  property bool vcExplicit: false
  property string vcSpec: ""
  property string vcDate: ""
  spacing: 8
  BigVideoThumb {
    host: vcell.host
    width: vcell.width
    height: Math.round(vcell.width * 9 / 16)
    url: vcell.artUrl
    urlBig: vcell.artBigUrl !== "" ? vcell.artBigUrl : vcell.artUrl
    videoId: vcell.vid
    vTitle: vcell.vcTitle
    vArtist: vcell.vcArtist
    vDuration: vcell.vcDuration
    // The resolution lives on the thumbnail, not beside the title:
    // a tag there ate most of the title on typical song names.
    spec: vcell.vcSpec !== "" ? vcell.vcSpec : host.qualSpec("VIDEO")
  }
  Item {
    width: vcell.width
    height: vMetaCol.height
    Column {
      id: vMetaCol
      anchors.left: parent.left
      anchors.top: parent.top
      width: parent.width - vDl.width - 12
      spacing: 4
      Item {
        width: parent.width
        height: 22
        readonly property real avail: width - (vExp.visible ? vExp.width + 6 : 0)
        Text {
          id: vTitleTx
          anchors.verticalCenter: parent.verticalCenter
          width: Math.max(0, Math.min(implicitWidth, parent.avail))
          textFormat: Text.PlainText
          text: vcell.vcTitle
          color: textHi
          font.pixelSize: 15
          font.bold: true
          elide: Text.ElideRight
          maximumLineCount: 1
        }
        ExplicitMark {
          id: vExp
          visible: vcell.vcExplicit
          anchors.left: vTitleTx.right
          anchors.leftMargin: 6
          anchors.verticalCenter: parent.verticalCenter
        }
      }
      // Baseline-aligned, not centred: the mono date and the UI-font
      // artist have different descents, so matching line boxes still
      // reads crooked.
      Item {
        width: parent.width
        // Never collapse: a video with no artist credits still
        // shows its date.
        height: Math.max(vArtists.height, 18)
        // The dot and date reserve their (short, fixed) width
        // first and the artist list clips to what remains, so a
        // long credit line cannot push the date out of the meta
        // column and under the download button.
        // Clamped to the column width so an extreme narrowing can
        // never push the dot + date past the meta column and under
        // the download button.
        readonly property real dateW: vDateTx.visible ? Math.min(width, vDot.implicitWidth + vDateTx.implicitWidth + 16) : 0
        ArtistLinks {
          id: vArtists
          host: vcell.host
          anchors.left: parent.left
          anchors.top: parent.top
          width: Math.max(0, Math.min(implicitWidth, parent.width - parent.dateW))
          artists: host.artistsById[vcell.vid] || []
        }
        Text {
          id: vDot
          visible: vcell.vcDate !== ""
          anchors.left: vArtists.right
          anchors.leftMargin: 8
          anchors.baseline: vArtists.baseline
          text: "·"
          color: textDim
          font.family: mono
          font.pixelSize: 11
        }
        Text {
          id: vDateTx
          visible: vcell.vcDate !== ""
          anchors.left: vDot.right
          anchors.leftMargin: 8
          anchors.baseline: vArtists.baseline
          textFormat: Text.PlainText
          text: vcell.vcDate
          color: textLo
          font.family: mono
          font.pixelSize: 11
        }
      }
    }
    DownloadButton {
      id: vDl
      host: vcell.host
      mediaId: vcell.vid
      ownedCheck: true
      label: "Download"
      noun: "video"
      chooserKind: "video"
      anchors.right: parent.right
      anchors.verticalCenter: vMetaCol.verticalCenter
      onTap: function () {
        waves.downloadVideo(vcell.vid)
      }
    }
  }
}

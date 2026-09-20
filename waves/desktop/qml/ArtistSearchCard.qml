import QtQuick
import QtQuick.Layouts

// Shared artist search-result card. Used by both the collapsed horizontal
// strip and the expanded fill grid, so its data comes in as plain properties
// (not model roles): a top-level component sits outside the Repeater delegate
// scope, so the delegate wires model.art/name/popularity/id into these.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.hoverPrefetch / host.hoverPrefetchCancel
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: asc
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color textHi: "#e6e8ec"

  property string aArt: ""
  property string aName: ""
  property real aPop: 0
  property string aId: ""
  radius: 12
  color: surface
  border.color: border1
  // Resting anywhere on the card has its page ready before the click
  // (see hoverPrefetch). Its own handler, the way BrowseCard's is.
  readonly property var prefetchCard: ({
      kind: "artist",
      id: asc.aId,
      art: asc.aArt
    })
  HoverHandler {
    onHoveredChanged: hovered ? host.hoverPrefetch(asc.prefetchCard) : host.hoverPrefetchCancel(asc.prefetchCard)
  }
  // Size to the content (plus the 8px top and bottom margins) so the card
  // height matches art + name + meter + preview + download exactly.
  implicitHeight: cardCol.implicitHeight + 16
  Column {
    id: cardCol
    anchors.fill: parent
    anchors.margins: 8
    spacing: 8
    Art {
      host: asc.host
      width: parent.width
      height: parent.width
      hoverFx: true
      fxKind: "artist"
      fxId: aId
      url: aArt
      // What you already hold by this artist, said as a strip across
      // the cover's lower edge rather than a chip dropped in a
      // corner: the one row of a search page that stayed silent about
      // the library now answers, and no face is covered to say it. A
      // child of the Art, so it takes the cover's tilt, hover lift
      // and rounded clip for free.
      ArtistBadges {
        host: asc.host
        bar: true
        width: parent.width
        anchors.bottom: parent.bottom
        artistName: aName
      }
    }
    Text {
      textFormat: Text.PlainText
      text: aName
      color: textHi
      font.pixelSize: 14
      font.bold: true
      elide: Text.ElideRight
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
    }
    PopMeter {
      host: asc.host
      anchors.horizontalCenter: parent.horizontalCenter
      value: aPop
    }
    // Preview + Download live in the card body (never overlaid on the
    // photo); each has its own MouseArea that consumes the click so the
    // card-wide open-artist MouseArea (z:-1, below) only fires elsewhere.
    // Preview plays the artist's top track and doubles as a scrubber.
    PreviewBar {
      host: asc.host
      width: parent.width
      pid: aId
    }
    DownloadButton {
      host: asc.host
      objectName: "artistCardDownload"
      width: parent.width
      mediaId: aId
      chooserKind: "artist"
      label: "Download artist"
      // A card is a surface too: the same capability verdict the
      // artist page's control reads keeps an Apple artist card from
      // offering a sweep its catalog cannot run.
      visible: waves.artistDownloadSupported(aId)
      // What the strip on the cover already says, said again by the
      // control that would act on it: a catalogue you partly hold
      // is not a fresh grab.
      libArtist: aName
      onTap: function () {
        waves.downloadArtist(aId)
      }
    }
  }
  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    z: -1
    onClicked: waves.loadArtist(aId)
  }
}

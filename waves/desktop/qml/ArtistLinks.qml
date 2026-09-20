import QtQuick

// A line of comma-separated artist names, each individually clickable.
// 'host' is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load. The row reads through it:
//   host.onArtistPage(id) / host.onAlbumPage(id)  “already open” checks
//   host.openAlbumPage(albumId, highlight, title)  the suffix's action
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Row {
  id: al
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color textLo: "#a8acb4"
  property var artists: []
  property string suffix: ""
  property string albumId: ""      // set -> the suffix (album name) links to the album page
  property int px: 12
  clip: true
  // A Row has no baseline of its own; publish the name text's so callers
  // can baseline-align a date or tag sitting beside it (centring two
  // fonts with different descents reads crooked).
  FontMetrics {
    id: alFm
    font.pixelSize: al.px
  }
  baselineOffset: alFm.ascent
  Repeater {
    model: al.artists
    delegate: Row {
      required property var modelData
      required property int index
      Text {
        id: alName
        readonly property bool linkable: modelData.id && modelData.id !== "" && !host.onArtistPage(modelData.id)
        // Artist names stay accent-green even when inert (e.g. on
        // their own page), only the affordances go away.
        text: modelData.name
        textFormat: Text.PlainText
        color: accent
        font.pixelSize: al.px
        font.underline: alMa.containsMouse && linkable
        MouseArea {
          id: alMa
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: alName.linkable ? Qt.PointingHandCursor : Qt.ArrowCursor
          onClicked: if (alName.linkable)
            waves.loadArtist(modelData.id)
        }
      }
      Text {
        visible: index < al.artists.length - 1
        text: ", "
        color: textLo
        font.pixelSize: al.px
      }
    }
  }
  Text {
    visible: al.suffix !== ""
    textFormat: Text.PlainText
    text: " · "
    color: textLo
    font.pixelSize: al.px
  }
  Text {
    id: alSuffix
    readonly property bool linkable: al.albumId !== "" && !host.onAlbumPage(al.albumId)
    visible: al.suffix !== ""
    textFormat: Text.PlainText
    text: al.suffix
    color: alSfMa.containsMouse && linkable ? "#ffffff" : textLo
    font.pixelSize: al.px
    font.underline: alSfMa.containsMouse && linkable
    MouseArea {
      id: alSfMa
      anchors.fill: parent
      enabled: alSuffix.linkable
      hoverEnabled: enabled
      cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: host.openAlbumPage(al.albumId, "", al.suffix)
    }
  }
}

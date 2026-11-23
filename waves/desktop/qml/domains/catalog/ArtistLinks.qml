import QtQuick
import QtQuick.Controls.Basic
import "../../primitives" as Primitives
import "../../primitives"

// A line of comma-separated artist names, each individually clickable.
// 'host' is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load. The row reads through it:
//   host.onArtistPage(id) / host.onAlbumPage(id)  “already open” checks
//   host.openAlbumPage(albumId, highlight, title)  the suffix's action
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Row {
  id: al
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color textLo: "#a8acb4"
  property var artists: []
  property string suffix: ""
  property string albumId: ""      // set -> the suffix (album name) links to the album page
  property int px: 12
  clip: true
  readonly property var namedArtists: artists.filter(function (artist) {
    return !!artist.name
  })
  readonly property string fullText: namedArtists.map(function (artist) {
    return artist.name
  }).join(", ") + (suffix ? (namedArtists.length ? " · " : "") + suffix : "")
  ToolTip.visible: alHover.hovered && implicitWidth > width + 1
  ToolTip.text: fullText
  HoverHandler {
    id: alHover
  }
  // A Row has no baseline of its own; publish the name text's so callers
  // can baseline-align a date or tag sitting beside it (centring two
  // fonts with different descents reads crooked).
  FontMetrics {
    id: alFm
    font.pixelSize: al.px
  }
  baselineOffset: alFm.ascent
  Repeater {
    model: al.namedArtists
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
        TapAction {
          id: alMa
          anchors.fill: parent
          enabled: alName.linkable
          activeFocusOnTab: enabled && alName.parent.x < al.width
          accessibleLabel: "Open artist " + modelData.name
          onTriggered: waves.loadArtist(modelData.id)
        }
      }
      Text {
        visible: index < al.namedArtists.length - 1
        text: ", "
        color: textLo
        font.pixelSize: al.px
      }
    }
  }
  Text {
    visible: al.suffix !== "" && al.namedArtists.length > 0
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
    TapAction {
      id: alSfMa
      anchors.fill: parent
      enabled: alSuffix.linkable
      activeFocusOnTab: enabled && alSuffix.x < al.width
      accessibleLabel: "Open album " + al.suffix
      onTriggered: host.openAlbumPage(al.albumId, "", al.suffix)
    }
  }
}

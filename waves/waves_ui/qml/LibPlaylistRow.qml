import QtQuick
import QtQuick.Layouts

// One "My Music > Playlists" row: a playlist, or a playlist folder that
// drills in like a file manager. Shared by the root list and the
// drilled-in folder list.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.hoverPrefetch / host.hoverPrefetchCancel / host.openPlaylistPage
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Rectangle {
  id: plRow
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  required property var model
  // The source group that owns the drill-in this row opens: a folder
  // belongs to one source's shelf, so the group's own folder state
  // answers the click.
  property var folderHost: null
  width: ListView.view.width
  height: 64
  radius: 10
  color: surface
  border.color: border1
  readonly property bool isFolder: model.kind === "folder"
  // The whole row opens the playlist page: resting on it has the page
  // ready before the click (see hoverPrefetch). Folders drill in
  // locally and need nothing.
  readonly property var prefetchCard: ({
      kind: "playlist",
      id: "" + (model.id || ""),
      art: "" + (model.art || "")
    })
  HoverHandler {
    enabled: !plRow.isFolder
    onHoveredChanged: hovered ? host.hoverPrefetch(plRow.prefetchCard) : host.hoverPrefetchCancel(plRow.prefetchCard)
  }
  RowLayout {
    anchors.fill: parent
    anchors.margins: 10
    spacing: 13
    FolderTile {
      visible: plRow.isFolder
    }
    Art {
      host: plRow.host
      visible: !plRow.isFolder
      width: 44
      height: 44
      hoverFx: true
      fxKind: "playlist"
      fxId: plRow.isFolder ? "" : ("" + (model.id || ""))
      url: plRow.isFolder ? "" : model.art
    }
    ColumnLayout {
      Layout.fillWidth: true
      spacing: 2
      Text {
        textFormat: Text.PlainText
        text: model.title
        color: textHi
        font.pixelSize: 15
        font.bold: true
        elide: Text.ElideRight
        Layout.fillWidth: true
      }
      Text {
        textFormat: Text.PlainText
        text: plRow.isFolder ? model.sub : (model.tracks > 0 ? model.tracks + " tracks" : "Playlist")
        color: textLo
        font.pixelSize: 12
      }
    }
    DownloadButton {
      host: plRow.host
      visible: !plRow.isFolder
      mediaId: plRow.isFolder ? "" : model.id
      chooserKind: "playlist"
      collectionCheck: !plRow.isFolder
      label: "Download playlist"
      onTap: function () {
        waves.downloadPlaylist(model.id)
      }
    }
    Item {
      visible: plRow.isFolder
      implicitWidth: folderBtn.implicitWidth
      implicitHeight: folderBtn.implicitHeight
      // A folder rollup has no ownership record, so the button shows
      // live download state only (the discography precedent).
      DownloadButton {
        id: folderBtn
        host: plRow.host
        mediaId: plRow.isFolder ? plRow.model.id : ""
        chooserKind: "folder"
        label: "Download all"
        onTap: function () {
          waves.downloadFolder(folderBtn.mediaId)
        }
      }
      FolderBadge {
        host: plRow.host
        anchors.right: folderBtn.right
        anchors.rightMargin: -8
        anchors.top: folderBtn.top
        anchors.topMargin: -9
        folderId: folderBtn.mediaId
        total: plRow.isFolder ? (plRow.model.plCount || 0) : 0
        st: folderBtn.st
      }
    }
  }
  MouseArea {
    anchors.fill: parent
    z: -1
    cursorShape: Qt.PointingHandCursor
    onClicked: plRow.isFolder ? (plRow.folderHost ? plRow.folderHost.openFolder(plRow.model.id, plRow.model.title) : undefined) : host.openPlaylistPage(plRow.model.id, plRow.model.title, plRow.model.art)
  }
}

import QtQuick

// Search-results video thumbnail: the same peek behaviour as VideoThumb at
// 16:9 and several hundred pixels wide, with the duration in the corner.
// At this size a glance costs a real stream, so the dwell is longer and
// guarded: any movement inside the thumb restarts it (only a resting
// pointer counts) and a closed peek holds a brief cooldown, so a pointer
// crossing the grid never chain-fires previews.
// 'host' is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load. The thumb reads through it:
//   host.libraryOn / host.dlInLibrary  the owned-plate wording
//   host.peekNow / host.peekThumbHover / host.peekCooldown  shared peek state
//   host.peekOpen(anchor, id, title, artist, art) / host.peekClose() /
//     host.peekHoverCheck()  the peek actions
//   host.openVideo(id, title, artist)  the click action
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Item {
  id: bvt
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color gold: "#ffb01f"   // HI-RES / VIDEO tier + meter mid band
  readonly property color green: "#3ef08a"   // LOSSLESS tier + done state
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color textHi: "#e6e8ec"
  property string url: ""
  property string urlBig: ""
  property string videoId: ""
  property string vTitle: ""
  property string vArtist: ""
  property string vDuration: ""
  property string spec: ""
  readonly property bool peekable: videoId !== ""
  scale: peekable && bvtHover.hovered ? 1.03 : 1
  Behavior on scale {
    NumberAnimation {
      duration: 160
      easing.type: Easing.OutCubic
    }
  }
  z: bvtHover.hovered ? 4 : 0
  Art {
    host: bvt.host
    anchors.fill: parent
    radius: 8
    url: bvt.urlBig !== "" ? bvt.urlBig : bvt.url
  }
  PlayBadge {
    radius: 8
    lit: bvtHover.hovered
  }
  // "You already downloaded this" rides the top-LEFT corner, across from
  // the resolution badge: same plate, same size, green (the on-disk
  // owned colour). Videos never appear in the library scan (it only
  // walks audio), so the one truthful signal here is Waves' own
  // ownership record for this exact video id.
  property bool owned: false
  function _refreshOwned() {
    var o = bvt.videoId !== "" ? waves.ownershipOf(bvt.videoId) : ({})
    owned = o.owned === true
  }
  onVideoIdChanged: _refreshOwned()
  Component.onCompleted: _refreshOwned()
  Connections {
    target: waves
    // Empty id = broadcast (the quality setting changed).
    function onOwnershipChanged(tid) {
      if (tid === bvt.videoId || tid === "")
        bvt._refreshOwned()
    }
    function onOwnershipChangedBatch(batch) {
      if (bvt.videoId !== "" && batch.indexOf("," + bvt.videoId + ",") !== -1)
        bvt._refreshOwned()
    }
  }
  Rectangle {
    visible: bvt.owned
    anchors.left: parent.left
    anchors.top: parent.top
    anchors.margins: 6
    radius: 4
    color: "#cc06090c"
    implicitHeight: 18
    implicitWidth: bvtOwn.implicitWidth + 10
    Text {
      id: bvtOwn
      anchors.centerIn: parent
      // The same wording rule as the cell's own DownloadButton done
      // face (whose noun is "video"): one cell must never say
      // DOWNLOADED on the art and VIDEO IN LIBRARY on the button
      // for the same ownership record. A video is never in the
      // scan (audio only), so its libPresent is always false and
      // both faces reduce to libraryOn && dlInLibrary.
      textFormat: Text.PlainText
      text: host.libraryOn && host.dlInLibrary ? "IN LIBRARY" : "DOWNLOADED"
      color: green
      font.family: mono
      font.pixelSize: 10
    }
  }
  // Resolution rides the thumbnail's top-right corner (gold, the video
  // tier's colour), same plate as the duration below it. On a 16:9
  // thumbnail "video" goes without saying, so the badge is the spec
  // alone and the title below keeps its full width.
  Rectangle {
    visible: bvt.spec !== ""
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: 6
    radius: 4
    color: "#cc06090c"
    implicitHeight: 18
    implicitWidth: bvtSpec.implicitWidth + 10
    Text {
      id: bvtSpec
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: bvt.spec
      color: gold
      font.family: mono
      font.pixelSize: 10
    }
  }
  Rectangle {
    visible: bvt.vDuration !== ""
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.margins: 6
    radius: 4
    color: "#cc06090c"
    implicitHeight: 18
    implicitWidth: bvtDur.implicitWidth + 10
    Text {
      id: bvtDur
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: bvt.vDuration
      color: textHi
      font.family: mono
      font.pixelSize: 10
    }
  }
  // Rest detection needs the pointer's own travel, not raw point
  // updates: art hover effects move the thumb under a still cursor,
  // which re-delivers hover events every frame. Restarting on those
  // would hold the dwell off forever, so only real movement past a
  // few pixels counts as "not resting yet".
  property real _restX: -1
  property real _restY: -1
  HoverHandler {
    id: bvtHover
    enabled: bvt.peekable
    onHoveredChanged: {
      if (hovered) {
        // Landing on a neighbour drops the open card at once:
        // peekThumbHover is shared, so without this a sideways
        // slide across the grid would pin the card open.
        if (host.peekNow && host.peekNow.id !== bvt.videoId)
          host.peekClose()
        host.peekThumbHover = true
        bvt._restX = point.scenePosition.x
        bvt._restY = point.scenePosition.y
        bvtDwell.restart()
      } else {
        bvtDwell.stop()
        host.peekThumbHover = false
        host.peekHoverCheck()
      }
    }
    onPointChanged: {
      if (!hovered || !bvtDwell.running)
        return
      var dx = point.scenePosition.x - bvt._restX
      var dy = point.scenePosition.y - bvt._restY
      if (dx * dx + dy * dy < 16)
        // within 4px: still resting
        return
      bvt._restX = point.scenePosition.x
      bvt._restY = point.scenePosition.y
      bvtDwell.restart()
    }
  }
  Timer {
    id: bvtDwell
    interval: 700
    onTriggered: {
      if (!bvtHover.hovered)
        return
      if (host.peekCooldown) {
        bvtDwell.restart()
        return
      }
      host.peekOpen(bvt, bvt.videoId, bvt.vTitle, bvt.vArtist, bvt.urlBig !== "" ? bvt.urlBig : bvt.url)
    }
  }
  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    z: -1
    onClicked: host.openVideo(bvt.videoId, bvt.vTitle, bvt.vArtist)
  }
}

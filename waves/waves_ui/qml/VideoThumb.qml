import QtQuick

// Small square video thumbnail (the peek's source): art, play badge and explicit mark.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.peekHoverCheck / host.peekOpen / host.peekThumbHover
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Item {
  id: vt
  required property var host

  property string url: ""
  property bool lit: false
  // Hover peek wiring: with a videoId set, the thumb swells right away
  // for instant feedback and a short dwell grows the floating peek
  // card out of its rect (host.peekOpen). Thumbs without an id (none
  // today) stay inert.
  property string videoId: ""
  property string vTitle: ""
  property string vArtist: ""
  readonly property bool peekable: videoId !== ""
  width: 88
  height: 50
  scale: peekable && vtHover.hovered ? 1.08 : 1
  Behavior on scale {
    NumberAnimation {
      duration: 160
      easing.type: Easing.OutCubic
    }
  }
  z: vtHover.hovered ? 4 : 0
  Art {
    host: vt.host
    anchors.fill: parent
    radius: 6
    url: vt.url
  }
  PlayBadge {
    lit: vt.lit || vtHover.hovered
  }
  HoverHandler {
    id: vtHover
    enabled: vt.peekable
    onHoveredChanged: {
      if (hovered) {
        host.peekThumbHover = true
        vtDwell.restart()
      } else {
        vtDwell.stop()
        host.peekThumbHover = false
        host.peekHoverCheck()
      }
    }
  }
  Timer {
    id: vtDwell
    interval: 450
    onTriggered: if (vtHover.hovered)
      host.peekOpen(vt, vt.videoId, vt.vTitle, vt.vArtist, vt.url)
  }
}

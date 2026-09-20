import QtQuick

// Count badge on a folder's "Download all" button. Idle: the folder's
// playlist total. Running: playlists remaining, rolling down one tick per
// completed playlist; the last tick rolls in a checkmark, holds a beat,
// then the badge shrinks and fades away with the button flipped to done.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.folderRemainMap
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: fb
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg

  property string folderId: ""
  property int total: 0
  property string st: ""   // the folder DownloadButton's st
  readonly property string value: {
    // "failed" reads as idle again: _bump_folder_group emits
    // folderRemaining(fid, 0, total) for a failed member as well as a
    // done one, so a tick here would paint green success straight over
    // the red RETRY button, and it would never clear (the dismissal
    // Timer only arms for "done"). The total is what RETRY re-queues.
    var m = host.folderRemainMap
    var known = m[folderId] !== undefined
    if (st === "" || st === "queued" || st === "preparing" || st === "failed")
      return total > 0 ? "" + total : (known ? "" + m[folderId] : "")
    var r = known ? m[folderId] : total
    // A count nobody has published yet is not zero. The Browse category
    // badge has no total to fall back on (a category's size is only
    // known once it resolves), so it read "0" and odometer-rolled up to
    // N. Blank until there is a real number to show.
    if (!known && total <= 0)
      return ""
    return r > 0 ? "" + r : "✓"
  }
  property bool gone: false
  onStChanged: if (st !== "done")
    gone = false
  Timer {
    running: fb.st === "done" && !fb.gone
    interval: 700
    onTriggered: fb.gone = true
  }
  implicitHeight: 21
  implicitWidth: Math.max(21, digit.implicitWidth + 12)
  radius: height / 2
  color: accentCont
  border.width: 1.4
  border.color: accent
  opacity: gone ? 0 : 1
  scale: gone ? 0.3 : 1
  visible: opacity > 0.01 && value !== ""   // an empty pill says nothing
  Behavior on opacity {
    NumberAnimation {
      duration: 420
      easing.type: Easing.InQuad
    }
  }
  Behavior on scale {
    NumberAnimation {
      duration: 420
      easing.type: Easing.InBack
    }
  }
  OdoDigit {
    id: digit
    anchors.centerIn: parent
    value: fb.value
  }
}

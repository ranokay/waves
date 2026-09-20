import QtQuick

// The app-wide breadcrumb trail (folder-strip pills over navHistory +
// the current page as the last, lit pill; see crumbBase for why the trail
// is only this section's slice of it). Crumb click = navTo(crumbBase + ord).
// Long trails fold the middle behind a "…" pill that expands in place
// and morphs into "›‹" to fold back; navigating deeper auto-refolds.
// Motion: slot widths glide 220ms OutCubic while new crumbs rise in
// with the control bounce (the picked M3, gated on hoverMotion like
// RiseIn). The trail reconciles against crumbLabels instead of being
// rebuilt, so crumbs animate in and out rather than popping.
// `host` is Main.qml's root object, bound at both instantiations (the
// browse sub-page bar and the artist page's sticky bar) and required so
// a missed binding fails at load.
// It reads through it:
//   host.crumbBase / host.crumbLabels / host.crumbSynth /
//   host.crumbSynthGo / host.crumbTailPending / host.navTo
// Split out of Main.qml (#315 slice 9). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Item {
  id: nct
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color surface2: "#191c22"   // hover / nested
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  property int keepTail: 2
  property bool unfolded: false
  property int liveCount: 0
  implicitHeight: 26
  implicitWidth: rowNct.width
  readonly property bool foldable: liveCount > keepTail + 2
  readonly property bool folding: !unfolded && foldable
  readonly property var labels: host.crumbLabels
  // 0ms debounce: navigation flips several flags in one JS run; sync
  // once against the settled state, never a half-switched one.
  onLabelsChanged: nctSyncT.restart()
  Component.onCompleted: sync()
  Timer {
    id: nctSyncT
    interval: 0
    onTriggered: nct.sync()
  }
  ListModel {
    id: nctModel
  }
  // Reconcile the pill model against the wanted labels: shared prefix
  // stays, dropped crumbs animate out (dying), new ones animate in.
  // "ord" is each live pill's position in the trail; dying pills keep a
  // stale ord but nothing reads it.
  function sync() {
    var want = labels
    var have = [], haveIdx = []
    for (var i = 0; i < nctModel.count; i++)
      if (!nctModel.get(i).dying) {
        have.push(nctModel.get(i).tag)
        haveIdx.push(i)
      }
    var k = 0
    while (k < have.length && k < want.length && have[k] === want[k])
      k++
    if (want.length === have.length && k === have.length - 1) {
      // Only the current page's label changed (a late-loading
      // title): swap the text in place, no churn.
      nctModel.setProperty(haveIdx[k], "tag", want[k])
      return
    }
    var cutAny = false
    for (var c = k; c < have.length; c++) {
      nctModel.setProperty(haveIdx[c], "dying", true)
      cutAny = true
    }
    for (var a = k; a < want.length; a++)
      nctModel.append({
        tag: want[a],
        dying: false,
        ord: a
      })
    if (want.length > have.length)
      unfolded = false
    // deeper: refold
    var ord = 0
    for (i = 0; i < nctModel.count; i++)
      if (!nctModel.get(i).dying)
        nctModel.setProperty(i, "ord", ord++)
    liveCount = want.length
    if (cutAny)
      nctReap.restart()
  }
  Timer {
    // Just past the 90ms removal fade: dying pills leave as soon as
    // they are invisible, so the row closes up right behind the fade.
    id: nctReap
    interval: 110
    onTriggered: {
      for (var i = nctModel.count - 1; i >= 0; i--)
        if (nctModel.get(i).dying)
          nctModel.remove(i)
    }
  }
  Row {
    id: rowNct
    spacing: 0
    height: parent.height
    Repeater {
      model: nctModel
      delegate: Item {
        id: nc
        required property string tag
        required property bool dying
        required property int ord
        // Lit and unclickable because it IS the page you are on.
        // While the current page is still nameless its crumb is
        // held back, so the tail pill is only the parent: leave it
        // ordinary and clickable (host.crumbTailPending).
        readonly property bool isLast: !dying && ord === nct.liveCount - 1 && !host.crumbTailPending
        readonly property bool foldedOut: nct.folding && !dying && ord > 0 && ord <= nct.liveCount - 1 - nct.keepTail
        readonly property bool foldShown: nct.foldable && !dying && ord === 1
        readonly property bool crumbHidden: dying || foldedOut
        readonly property bool sepHidden: dying || (foldedOut && !foldShown)
        height: 26
        width: ncRow.width
        clip: true
        Row {
          id: ncRow
          spacing: 0
          height: parent.height
          // No entrance/width animation anywhere in the trail:
          // pills growing in per navigation read as a wipe
          // (reported from livetesting). Crumbs appear in place;
          // the only motion left is a quick fade on removal.
          // separator slot
          Item {
            height: parent.height
            clip: true
            width: (nc.ord > 0 && !nc.sepHidden) ? ncSep.implicitWidth + 12 : 0
            Text {
              id: ncSep
              anchors.centerIn: parent
              textFormat: Text.PlainText
              text: "›"
              color: textDim
              font.pixelSize: 13
            }
          }
          // fold-mark slot: "…" while folded, "›‹" once expanded
          Item {
            height: parent.height
            clip: true
            width: nc.foldShown ? ncFoldPill.implicitWidth + (nct.folding ? 0 : 6) : 0
            opacity: nc.foldShown ? 1 : 0
            Behavior on opacity {
              NumberAnimation {
                duration: 90
              }
            }
            Rectangle {
              id: ncFoldPill
              radius: 8
              height: 26
              anchors.verticalCenter: parent.verticalCenter
              implicitWidth: ncFoldTx.implicitWidth + 20
              width: implicitWidth
              color: surface2
              border.color: border1
              Text {
                id: ncFoldTx
                anchors.centerIn: parent
                textFormat: Text.PlainText
                text: nct.folding ? "…" : "›‹"
                color: ncFoldMa.containsMouse ? textHi : textLo
                font.pixelSize: 12
              }
            }
            MouseArea {
              id: ncFoldMa
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: nct.unfolded = !nct.unfolded
            }
          }
          // crumb slot
          Item {
            height: parent.height
            clip: true
            width: nc.crumbHidden ? 0 : ncPill.implicitWidth
            opacity: nc.crumbHidden ? 0 : 1
            Behavior on opacity {
              NumberAnimation {
                duration: 90
              }
            }
            Rectangle {
              id: ncPill
              radius: 8
              height: 26
              anchors.verticalCenter: parent.verticalCenter
              implicitWidth: ncTx.implicitWidth + 20
              width: implicitWidth
              color: nc.isLast ? accentCont : surface2
              border.color: nc.isLast ? accentDim : border1
              Behavior on color {
                ColorAnimation {
                  duration: 200
                }
              }
              Behavior on border.color {
                ColorAnimation {
                  duration: 200
                }
              }
              Text {
                id: ncTx
                anchors.centerIn: parent
                textFormat: Text.PlainText
                text: nc.tag
                color: nc.isLast ? accent : textLo
                Behavior on color {
                  ColorAnimation {
                    duration: 200
                  }
                }
                font.pixelSize: 12
                font.bold: nc.isLast
              }
            }
            MouseArea {
              anchors.fill: parent
              hoverEnabled: true
              enabled: !nc.isLast && !nc.crumbHidden
              cursorShape: Qt.PointingHandCursor
              // ord is the pill's place in the TRAIL; navTo
              // indexes the whole history, which the trail is
              // a tail slice of (host.crumbBase). A synthetic
              // section-root pill (host.crumbSynth) leads the
              // trail without a history entry behind it: it
              // climbs out of the drill instead, and shifts
              // every later pill's history index by one.
              onClicked: {
                if (host.crumbSynth && nc.ord === 0)
                  host.crumbSynthGo()
                else
                  host.navTo(host.crumbBase + nc.ord - (host.crumbSynth ? 1 : 0))
              }
            }
          }
        }
      }
    }
  }
}

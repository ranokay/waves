import QtQuick

// The "in your library" presence pill: amber identity, compact and STATIC.
// The pill is color-coded by the QUALITY of the local copy (gold hi-res,
// green lossless, cyan healthy lossy, red small lossy, amber when unknown),
// and that colour is the whole quality story: no hover reveal, nothing
// resizes. It reports presence (a partial copy spells out N OF M); the
// prevention lives in the DownloadButton itself, which renders a full
// local copy as the inert DOWNLOADED state (see its lib* properties). A
// click opens the matched local album folder.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.browseBuilding / host.pillClassCont / host.pillClassDim /
//   host.pillClassFg / host.pillClassTx / host.searchBuilding
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: pxt
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)

  property int have: 0
  property int total: 0
  property string albumId: ""        // the matched album's folder path
  property string qclass: ""         // quality class (presence local_class)
  // Any copy short of the full count spells out N OF M. The strict bar
  // for the inert DOWNLOADED claim is local >= total with no slack
  // (matching.decide_presence), and this must agree with it: an earlier
  // "total - 1" here let a 9-of-10 copy wear an unqualified IN LIBRARY
  // pill beside a still-live DOWNLOAD button.
  // What the LOCAL release says it holds, which is not always what the
  // album on screen holds. N OF M counts against whichever total the copy
  // falls short of: normally the album being viewed, but a folder holding
  // 14 files of a 63-track set beside a 14-track edition is short by its
  // OWN reckoning, and that is the number explaining the still-live
  // download button. Reading a flat IN LIBRARY over it is the one thing
  // the pill must not do.
  property int declared: 0
  readonly property int want: pxt.declared > pxt.have ? pxt.declared : pxt.total
  readonly property bool partial: pxt.have > 0 && pxt.want > 0 && pxt.have < pxt.want
  // A trailing micro-word for the pill's last position (the album
  // pill's " · ATMOS TOO"). Empty everywhere else, so every other
  // pill reads exactly as before; the pill's width follows pxBase.
  property string extra: ""
  // True when the match's IDENTITY is proven (exact edition title, both
  // years agreeing): the "?" is reserved for matches the matcher could
  // not prove are the same album. Coverage is a separate axis, already
  // spelled out as N OF M.
  property bool proven: false
  // A badge the page was BUILT with is simply there; a badge the scan
  // finds while you are already looking ARRIVES. News in this app fades
  // in, over the same 180ms the reveal itself uses, instead of snapping
  // into place a second after you started reading.
  //
  // The build flags cannot tell those apart on their own: they only cover
  // a fresh search or Browse build, so navigating BACK to a page, or a
  // row recycling under a scroll, animated pills that were never news and
  // left the page assembling itself in front of the reader. _settled is
  // the real question. It flips one event-loop pass after this pill is
  // created, which is late enough that the pill's first state is already
  // decided and early enough to catch anything the scan publishes after.
  // A Timer rather than Component.onCompleted, because call sites declare
  // their own onCompleted and would silently replace it.
  // Gated on visible, not replacing it: an invisible pill must still take
  // no layout width, which opacity alone would not do.
  //
  // Creation is only half of it. These pills outlive the thing they
  // describe: a list delegate is RECYCLED onto the next album as you
  // scroll, and the album header's single pill is rebound on every page
  // you open. Neither is news, and a latch that only ever flipped once
  // faded both. settleKey is whatever this pill is currently about, so
  // changing it re-arms the latch and the next answer is simply there.
  property string settleKey: ""
  property bool _settled: false
  onSettleKeyChanged: {
    pxt._settled = false
    pxtSettle.restart()
  }
  Timer {
    id: pxtSettle
    interval: 0
    running: true
    onTriggered: pxt._settled = true
  }
  opacity: pxt.visible ? 1 : 0
  Behavior on opacity {
    enabled: pxt._settled && !host.searchBuilding && !host.browseBuilding
    NumberAnimation {
      duration: 180
      easing.type: Easing.OutQuad
    }
  }
  radius: 4
  color: host.pillClassCont(pxt.qclass)
  border.color: host.pillClassDim(pxt.qclass)
  border.width: 1
  implicitHeight: 18
  implicitWidth: (pxt.proven ? 14 : 24) + pxBase.implicitWidth
  // A question mark, not the quality dot it replaces: every one of these
  // pills is a TAG MATCH, an inference from what the files say about
  // themselves, and nothing here was watched being downloaded. The mark
  // says so at a glance and costs no width, sitting exactly where the eye
  // already lands. Quality is still the whole colour story (the mark
  // takes the same class colour the dot did); this only separates
  // "recognised on disk" from the app's own records, which never wear it.
  Text {
    id: pxMark
    textFormat: Text.PlainText
    x: 7
    anchors.verticalCenter: parent.verticalCenter
    width: 5
    horizontalAlignment: Text.AlignHCenter
    visible: !pxt.proven
    text: "?"
    color: host.pillClassFg(pxt.qclass)
    font.family: mono
    font.pixelSize: 10
    font.bold: true
  }
  Text {
    id: pxBase
    textFormat: Text.PlainText
    x: pxt.proven ? 7 : 17
    anchors.verticalCenter: parent.verticalCenter
    text: (pxt.partial ? (pxt.have + " OF " + pxt.want + " IN LIBRARY") : "IN LIBRARY") + pxt.extra
    color: host.pillClassTx(pxt.qclass)
    font.family: mono
    font.pixelSize: 9
    font.bold: true
  }
  MouseArea {
    anchors.fill: parent
    // Gated by VISIBILITY, not enabled: a disabled MouseArea still
    // owns its cursorShape in Qt, so an explicit ArrowCursor here sat
    // on top of whatever cursor the row underneath was showing. An
    // invisible one claims nothing.
    visible: pxt.albumId !== ""
    cursorShape: Qt.PointingHandCursor
    onClicked: waves.revealLibraryAlbum(pxt.albumId)  // open the album folder
  }
}

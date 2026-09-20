import QtQuick
import QtQuick.Controls.Basic

// Shared scroll pane for the two Browse surfaces (landing and drilled
// page). Each pane keeps its own contentY for its whole life, which is
// what makes Back land already positioned: nothing is restored because
// nothing was lost. What remains here is the machinery for CONTENT
// swaps under the user (a landing revalidate, a page revalidate,
// endless-scroll growth): the column collapses for the rebuild turn and
// the clamp would yank contentY toward the top, so the scroll range is
// padded up to the held spot while armed and the very first frame lands
// ON it, content filling in around it.
// `host` is Main.qml's root object, bound at both instantiations (the
// Browse landing and the drilled page) and required so a missed binding
// fails at load.
// It reads through it:
//   host.browseCanGrow / host.browseGrow / host.browsePage /
//   host.browsePageKey
// It writes one flag back: host.browseMoving (the pane's moving state).
Flickable {
  id: bsp
  required property var host

  // The content column this pane scrolls (wired by the instance).
  property Item col: null
  // What this pane currently shows; a hold or restore is tagged with
  // it so it only ever applies to the content it was taken against.
  // The landing never changes key (""); the drill pane binds the
  // page key.
  property string restoreKey: ""
  // Endless scroll is a drilled-listing concern only; the landing
  // must never grow the drill pane's section from its own geometry.
  property bool grows: false
  clip: true
  readonly property real realContentH: (col ? col.height : 0) + 32
  readonly property real restorePad: pendingRestoreY >= 0 ? Math.max(0, pendingRestoreY + height - realContentH) : 0
  contentWidth: width
  contentHeight: realContentH + restorePad
  ScrollBar.vertical: ScrollBar {}
  boundsBehavior: Flickable.StopAtBounds
  property real pendingRestoreY: -1
  property string pendingRestoreKey: ""
  // mayDisarm: only a real layout pass may spend the hold. Disarm only
  // once the REAL content (pad excluded) reaches the target: the pad
  // alone always satisfies the clamped check.
  function applyRestore(mayDisarm) {
    if (pendingRestoreY < 0 || restoreKey !== pendingRestoreKey)
      return
    contentY = Math.min(pendingRestoreY, Math.max(0, contentHeight - height))
    if (mayDisarm && Math.max(0, realContentH - height) >= pendingRestoreY)
      pendingRestoreY = -1
    // reached the target
  }
  // The reference the track-row shells size their "load me now" window
  // against. They read THIS, never the live contentY: a Loader
  // consults `asynchronous` once, when it is created, so binding
  // hundreds of row shells to contentY spent that many JS
  // re-evaluations per scrolled frame and could not change a single
  // row. Exact whenever a hold is armed (every path that swaps
  // content in place arms one first); free scrolling falls back to a
  // 10-row band, inside the 12 rows of slack the window carries.
  readonly property int rowBandH: 10 * 62
  readonly property real rowAnchorY: pendingRestoreY >= 0 ? pendingRestoreY : Math.floor(contentY / rowBandH) * rowBandH
  // Arm the hold-in-place across an in-place content swap. Runs for a
  // hidden pane too: a landing revalidating behind an open page still
  // collapses its column, and the clamp does not care about
  // visibility. Only a pane the user is actively dragging declines.
  function holdScroll() {
    if (contentY <= 0 || (visible && moving))
      return
    pendingRestoreKey = restoreKey
    pendingRestoreY = contentY
  }
  // A fresh page (drill-in, stack pop) starts at the top; a Back that
  // armed a hold keeps its spot instead, applied in the SAME pass
  // (before paint) so there is never a visible jump from the top.
  onRestoreKeyChanged: {
    if (pendingRestoreY >= 0 && restoreKey === pendingRestoreKey)
      applyRestore(false)
    else
      contentY = 0
  }
  onMovingChanged: host.browseMoving = moving
  onPendingRestoreYChanged: if (pendingRestoreY >= 0)
    bspGiveUp.restart()
  // Watch the REAL height, not contentHeight: while a hold is armed
  // the pad absorbs growth (contentHeight stays constant), so a
  // contentHeight watcher would starve both the disarm check and the
  // endless-scroll top-up until the give-up timer fired.
  onRealContentHChanged: {
    applyRestore(true)
    maybeGrow()
  }
  // Give-up: the content never grew back to the held spot (it truly
  // changed). Drop the pad and settle at the real bottom.
  Timer {
    id: bspGiveUp
    interval: 800
    onTriggered: {
      bsp.pendingRestoreY = -1
      bsp.returnToBounds()
    }
  }
  // Endless scroll on a drilled listing page (a full-listing grid or
  // track list, one section that fills the page). Nearing the bottom
  // fetches the next window. Multi-section pages (genre/mood) are
  // horizontal shelves plus preview rows that each carry their own
  // "show more", so the whole-page vertical scroll doesn't grow them.
  // Guarded by browseGrow's in-flight/exhausted checks, so re-fires
  // while sitting near the bottom are cheap no-ops.
  function maybeGrow() {
    if (!grows || host.browsePageKey === "" || !host.browsePage)
      return
    var secs = host.browsePage.sections || []
    if (secs.length !== 1 || !host.browseCanGrow(secs[0]))
      return
    if (contentY + height >= contentHeight - 800)
      host.browseGrow(secs[0])
  }
  onContentYChanged: maybeGrow()
}

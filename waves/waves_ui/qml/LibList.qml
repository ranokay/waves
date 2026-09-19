import QtQuick
import QtQuick.Controls.Basic

// A virtualised My Music list: only the rows in (and near) the viewport are
// instantiated, so a multi-thousand-item category renders instantly and
// scrolls smoothly. Each instance sets its own `cat`, `model` and `delegate`.
// It prefetches the next page as it scrolls and shows a footer while loading.
// Its `host` is NOT Main.qml's root object (unlike the other split files): it
// is the source group this pane belongs to, read for `category`,
// `loadingMore` and `maybeLoadMore` (see the property's own comment).
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
ListView {
  id: lv
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color textLo: "#a8acb4"

  property string cat: ""
  // The source group this pane belongs to: its category decides whether
  // this pane shows, and every load/pagination call goes through it (the
  // group names its source for the bridge).
  property var host: null
  // Inset the list itself (not the delegate's x) so rows sit 22px from
  // each edge, matching the search results' centered column. A vertical
  // ListView manages its delegates' x, so an `x: 22` on the delegate is
  // silently overridden to 0; insetting the view is the reliable way.
  anchors.fill: parent
  anchors.leftMargin: 22
  anchors.rightMargin: 22
  visible: !!host && host.category === cat
  clip: true
  spacing: 8
  cacheBuffer: 800
  reuseItems: true
  boundsBehavior: Flickable.StopAtBounds
  ScrollBar.vertical: ScrollBar {}
  // Pin the scroll spot across a revalidate refill (same pattern as the
  // playlist-folder list): the fill resets contentY, so the armed spot
  // is re-applied as the delegates lay out, until it is reachable. A
  // user drag disarms it, their hand always wins.
  property real pendingY: -1
  function applyRestore() {
    if (pendingY < 0)
      return
    var maxY = Math.max(0, contentHeight - height)
    contentY = Math.min(pendingY, maxY)
    if (maxY >= pendingY)
      pendingY = -1
  }
  onMovementStarted: pendingY = -1
  // Re-check on scroll AND on size/content changes: after a page is
  // appended (contentHeight grows) or if the first page doesn't fill the
  // viewport (so it can't scroll), contentY never changes on its own,
  // without these the loader would stall. All three are idempotent thanks
  // to the group's hasMore / loadingMore guards in maybeLoadMore.
  onContentYChanged: if (lv.host)
    lv.host.maybeLoadMore(lv, lv.cat)
  onContentHeightChanged: {
    applyRestore()
    if (lv.host)
      lv.host.maybeLoadMore(lv, lv.cat)
  }
  onHeightChanged: if (lv.host)
    lv.host.maybeLoadMore(lv, lv.cat)
  // Breathing space inside the scroll area (see BrowseScroll).
  header: Item {
    width: 1
    height: 8
  }
  footer: Item {
    width: lv.width
    height: (lv.host && lv.host.loadingMore && lv.host.category === lv.cat) ? 48 : 20
    Text {
      anchors.centerIn: parent
      visible: lv.host && lv.host.loadingMore && lv.host.category === lv.cat
      text: "Loading more…"
      color: textLo
      font.pixelSize: 13
    }
  }
}

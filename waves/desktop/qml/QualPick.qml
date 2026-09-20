import QtQuick
import QtQuick.Controls.Basic

// The quality badge you can choose a tier on: the row's
// QualTag, untouched at rest, that grows a caret when hovered and drops a
// menu of the four tiers when clicked. A choice repaints the pill in the
// tier's container colour (plain ground = the catalog says, tinted = you
// said) and holds until the item is given another tier: downloading at a
// chosen tier leaves the pill stating it, so the badge and the copy on
// disk agree. A track without a choice of its own follows its album's.
// The choice itself lives on the bridge (setQualityOverride), which is
// what every download path reads at queue time.
//
// Motion: the menu springs open and shrinks shut and a hovered row lifts,
// both elastic, but the pill itself only ever EASES (see swapMs), all
// under the hover-motion preference like every other control.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host._tierRank / host.hoverMotion / host.qualBg / host.qualBorder /
//   host.qualDot / host.qualFg / host.qualMenuWidth / host.qualOverrideFor /
//   host.qualSpecFg / host.qualTint / host.qualityOverrides /
//   host.targetTier / host.tierFloor
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Item {
  id: qpk
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color surface2: "#191c22"   // hover / nested

  property string mediaId: ""
  property string albumId: ""      // a track's album, whose choice it inherits
  property string catalog: ""      // the tier the catalog advertises (QualTag.q)
  property var mix: []             // QualTag.mix: the album spans tiers
  property bool pickable: true     // false for a video row
  readonly property var tiers: ["HI-RES", "LOSSLESS", "HIGH", "LOW"]
  readonly property string override: host.qualOverrideFor(mediaId, albumId)
  // The best tier on offer: a MIXED album's top rung, else the catalog's.
  readonly property string ceiling: (mix && mix.length > 1) ? "" + mix[0].q : catalog
  readonly property bool canPick: pickable && host._tierRank[ceiling] !== undefined
  readonly property bool tinted: override !== "" && override !== "DEFAULT"
  // What the pill states: the choice, floored by what the catalog can
  // land (an album's HI-RES choice on its LOSSLESS-only track says
  // LOSSLESS), else the catalog's own word.
  readonly property string shown: tinted ? host.tierFloor(override, ceiling) : catalog
  // The tier a download queued now would ask for, the row the menu checks.
  readonly property string effective: tinted ? shown : host.tierFloor(host.targetTier, ceiling)
  readonly property bool hot: canPick && (hoverMa.containsMouse || menuOpen)
  // The menu is BUILT ON THE FIRST PRESS, never with the badge. A
  // results page carries one of these on every row, and the menu is some
  // thirty objects (a Popup, its ground, four rows with their own
  // easings and mouse areas); built eagerly, every row scrolled past
  // paid for a menu almost none of them ever open. Measured over a
  // 300-row sweep: 1.4s of delegate work had become 2.0s.
  property bool menuBuilt: false
  // For the scenario test, which cannot reach a Popup through children.
  readonly property bool menuOpen: menuLoader.item !== null && menuLoader.item.visible
  readonly property Item menuRows: menuLoader.item ? menuLoader.item.contentItem : null
  // The tier the copy already on disk was delivered at (backend
  // ownedTierOf: for an album, only when every track of it is owned,
  // and then the weakest one's tier). The menu marks that row with the
  // library word, so a tier you already hold is not asked for again by
  // mistake. ASKED WHEN THE MENU OPENS, never bound: a page of badges
  // must not each query the ownership cache on every paint, and the
  // answer is only ever read inside the open menu.
  property string ownedTier: ""
  readonly property bool anyNotOffered: !offered(tiers[0])
  readonly property int menuW: host.qualMenuWidth(anyNotOffered, ownedTier !== "")
  function refreshOwnedTier() {
    ownedTier = (canPick && mediaId !== "") ? ("" + (waves.ownedTierOf(mediaId) || "")) : ""
  }
  onMenuOpenChanged: if (menuOpen)
    refreshOwnedTier()
  function toggleMenu() {
    if (!canPick)
      return
    menuBuilt = true
    // a Loader builds synchronously, so item is there below
    var m = menuLoader.item
    if (!m)
      return
    if (m.visible)
      m.close()
    else
      m.open()
  }
  function closeMenu() {
    if (menuLoader.item)
      menuLoader.item.close()
  }
  function offered(t) {
    return ceiling === "" || host._tierRank[t] >= host._tierRank[ceiling]
  }
  function choose(t) {
    closeMenu()
    // Choosing the Settings tier is "no choice", unless the album
    // chose otherwise: then it is a choice this track keeps, pinned as
    // DEFAULT so the album's does not reach it.
    var albumChose = qpk.albumId !== "" && host.qualityOverrides[qpk.albumId] !== undefined
    var v = t === host.targetTier ? (albumChose ? "DEFAULT" : "") : t
    waves.setQualityOverride(qpk.mediaId, v)
  }
  implicitWidth: tag.implicitWidth - extraW
  implicitHeight: 22
  // The pill's colours ease between tiers on a pick, and its edge lights
  // under the pointer; the caret's room grows with a spring.
  property color pillBg: tinted ? host.qualTint(shown) : host.qualBg(shown)
  property color pillEdge: hot ? host.qualFg(shown) : host.qualBorder(shown)
  property color pillInk: host.qualFg(shown)
  property color pillSpecInk: host.qualSpecFg(shown)
  property color pillDot: host.qualDot(shown)
  property real extraW: hot ? 14 : 0
  // A tier landing on the pill is ONE change: ground, border, dot, word
  // ink, spec ink and the pill's own width all move together, on one
  // curve, over one duration, with nothing leading and nothing lagging.
  // InOutSine leaves and arrives at zero speed, so the change has no
  // edge at either end. Rounds that cross-faded a whole second pill over
  // this one, or staggered the ink behind the ground, made every colour
  // arrive twice on two curves: that is what read as jerky.
  //
  // Letters are the one thing that cannot be interpolated, so they are
  // the one thing handled apart, and still inside this change: they dip
  // out over the first four tenths and back in over the rest, which puts
  // the badge's single wordless instant exactly where the colour is
  // halfway. Only ever one word on the pill, never two crossing.
  readonly property int swapMs: host.hoverMotion ? 340 : 0
  readonly property int dipOutMs: Math.round(swapMs * 0.4)
  readonly property int dipInMs: swapMs - dipOutMs
  property bool swapping: false
  Behavior on pillBg {
    ColorAnimation {
      duration: qpk.swapMs
      easing.type: Easing.InOutSine
    }
  }
  // The edge answers the pointer as well as a pick, and hover has to
  // stay quick: a swap borrows the long curve, hover keeps its own.
  Behavior on pillEdge {
    ColorAnimation {
      duration: qpk.swapping ? qpk.swapMs : (host.hoverMotion ? 160 : 0)
      easing.type: Easing.InOutSine
    }
  }
  Behavior on pillInk {
    ColorAnimation {
      duration: qpk.swapMs
      easing.type: Easing.InOutSine
    }
  }
  Behavior on pillSpecInk {
    ColorAnimation {
      duration: qpk.swapMs
      easing.type: Easing.InOutSine
    }
  }
  Behavior on pillDot {
    ColorAnimation {
      duration: qpk.swapMs
      easing.type: Easing.InOutSine
    }
  }
  Behavior on extraW {
    NumberAnimation {
      duration: host.hoverMotion ? 220 : 0
      easing.type: Easing.OutBack
    }
  }
  // The pill's width, eased only THROUGH a swap: at rest and on hover it
  // tracks the content exactly, so the caret's room keeps its own
  // spring. Left easing, a hover would glide the caret in instead.
  property real pillW: tag.naturalW
  Behavior on pillW {
    enabled: qpk.swapping
    NumberAnimation {
      duration: qpk.swapMs
      easing.type: Easing.InOutSine
    }
  }
  // A choice landing (or being cleared) swaps the pill. Armed only once
  // the badge has settled on its identity: a recycled list delegate
  // (reuseItems) rebinding to the next row's item changes the override
  // too, and that is not news (DownloadButton's rollReady rule).
  property bool armed: false
  Timer {
    id: armTimer
    interval: 0
    onTriggered: qpk.armed = true
  }
  Component.onCompleted: {
    lastFace = face
    armTimer.restart()
  }
  onMediaIdChanged: {
    armed = false
    armTimer.restart()
    ownedTier = ""
  }
  // What the pill actually DRAWS, which is not the same question as
  // which tier is chosen: choosing the tier a plain pill already states
  // only tints it (colour alone, no dip), while choosing anything on a
  // MIXED album replaces its whole face even when `shown` is unmoved.
  readonly property string face: (mix && mix.length > 1 && !tinted) ? "MIXED" : shown
  property string lastFace: ""
  // Colour and width ease on ANY choice; the letters dip only when there
  // are different letters to arrive at.
  onOverrideChanged: if (armed && host.hoverMotion) {
    swapping = true
    swapDone.restart()
  }
  onFaceChanged: {
    var prev = lastFace
    lastFace = face
    if (armed && host.hoverMotion && prev !== "")
      startDip(prev)
  }
  // The letters on their way out, held here so the pill underneath can
  // turn immediately while they leave.
  property string ghostQ: ""
  property var ghostMix: []
  property bool ghosting: false
  property real ghostOp: 0
  property real inkOp: 1
  function startDip(prev) {
    dip.stop()
    ghostQ = prev === "MIXED" ? qpk.catalog : prev
    ghostMix = prev === "MIXED" ? qpk.mix : []
    ghostOp = 1
    inkOp = 0
    ghosting = true
    swapping = true
    dip.restart()
    swapDone.restart()
  }
  SequentialAnimation {
    id: dip
    NumberAnimation {
      target: qpk
      property: "ghostOp"
      from: 1
      to: 0
      duration: qpk.dipOutMs
      easing.type: Easing.InOutSine
    }
    NumberAnimation {
      target: qpk
      property: "inkOp"
      from: 0
      to: 1
      duration: qpk.dipInMs
      easing.type: Easing.InOutSine
    }
  }
  Timer {
    // Everything the swap borrowed goes back, or the next one starts
    // from halfway through the last. The width easing switching off
    // again is the one that matters most (see pillW).
    id: swapDone
    interval: qpk.swapMs + 90
    onTriggered: {
      qpk.ghosting = false
      qpk.swapping = false
      qpk.ghostOp = 0
      qpk.inkOp = 1
    }
  }
  QualTag {
    id: tag
    host: qpk.host
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    q: qpk.shown
    mix: qpk.tinted ? [] : qpk.mix
    bg: qpk.pillBg
    edge: qpk.pillEdge
    ink: qpk.pillInk
    specInk: qpk.pillSpecInk
    dotInk: qpk.pillDot
    extraW: qpk.extraW
    pillW: qpk.pillW
    contentOpacity: qpk.inkOp
  }
  // The outgoing letters, drawn with no ground and no border directly
  // over the arriving ones and centred on the same pill, so this badge
  // carries exactly one ground and one border at every instant of the
  // change. Frozen to the tier being left, colours included: the live
  // pill's are already on their way elsewhere. Built only for the
  // fraction of a second a tier is actually leaving: a second pill on
  // every row of a results page is a whole pill's worth of work per row,
  // for a change almost no row ever makes.
  Loader {
    anchors.centerIn: tag
    active: qpk.ghosting
    sourceComponent: QualTag {
      host: qpk.host
      opacity: qpk.ghostOp
      chromeless: true
      q: qpk.ghostQ
      mix: qpk.ghostMix
      ink: host.qualFg(qpk.ghostQ)
      specInk: host.qualSpecFg(qpk.ghostQ)
      dotInk: host.qualDot(qpk.ghostQ)
      extraW: qpk.extraW
    }
  }
  MouseArea {
    id: hoverMa
    anchors.fill: tag
    enabled: qpk.canPick
    hoverEnabled: enabled
    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
    onClicked: qpk.toggleMenu()
  }
  // The caret, built the first time the pointer reaches this badge: at
  // rest it is fully transparent, so a row scrolled past has nothing to
  // show and nothing to pay for. Once built it stays, since a badge the
  // pointer found once it will find again.
  property bool caretBuilt: false
  onHotChanged: if (hot)
    caretBuilt = true
  Loader {
    active: qpk.caretBuilt
    x: tag.x + tag.width - 17
    y: (qpk.height - 12) / 2
    sourceComponent: ExpandChevron {
      visible: qpk.canPick
      tile: 12
      glyph: 10
      showTile: false
      closedAngle: 0
      openAngle: 180
      stroke: host.qualFg(qpk.shown)
      open: qpk.menuOpen
      opacity: qpk.hot ? 1 : 0
      Behavior on opacity {
        NumberAnimation {
          duration: host.hoverMotion ? 140 : 0
        }
      }
    }
  }
  Loader {
    id: menuLoader
    active: qpk.menuBuilt
    sourceComponent: menuComp
  }
  Component {
    id: menuComp
    Popup {
      id: menu
      // Parented to the PILL, not this item: the pill overflows this
      // item's left edge while it holds its caret, and a press on that
      // overflow must count as a press on the pill (which toggles), not
      // as a press outside (which would close, then reopen).
      parent: tag
      x: tag.width - width
      y: tag.height + 4
      width: qpk.menuW
      padding: 4
      modal: false
      focus: true
      closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
      transformOrigin: Item.Top
      background: Rectangle {
        radius: 8
        color: surface2
        border.color: outline
      }
      contentItem: Column {
        objectName: "qualPickRows"
        spacing: 2
        Repeater {
          model: qpk.tiers
          delegate: QualPickRow {
            host: qpk.host
            required property string modelData
            pick: qpk
            t: modelData
          }
        }
      }
      // A cold ownership answer lands a beat after the menu opened, and
      // a download landing while it is open changes the answer too.
      // Coalesced: a launch-time flood of answers is one refresh, not
      // hundreds. Lives with the menu, so a badge nobody opened watches
      // nothing.
      Timer {
        id: ownAgain
        interval: 60
        onTriggered: qpk.refreshOwnedTier()
      }
      Connections {
        target: waves
        enabled: menu.visible
        // An album's answer is a roll-up of ids this badge does not
        // hold, so any answer landing is reason enough to re-ask.
        function onOwnershipChanged(tid) {
          ownAgain.restart()
        }
        function onOwnershipChangedBatch(batch) {
          ownAgain.restart()
        }
      }
      enter: Transition {
        ParallelAnimation {
          NumberAnimation {
            property: "opacity"
            from: 0
            to: 1
            duration: host.hoverMotion ? 120 : 0
          }
          NumberAnimation {
            property: "scale"
            from: 0.8
            to: 1
            duration: host.hoverMotion ? 260 : 0
            easing.type: Easing.OutBack
          }
        }
      }
      exit: Transition {
        ParallelAnimation {
          NumberAnimation {
            property: "opacity"
            from: 1
            to: 0
            duration: host.hoverMotion ? 110 : 0
          }
          NumberAnimation {
            property: "scale"
            from: 1
            to: 0.9
            duration: host.hoverMotion ? 110 : 0
            easing.type: Easing.InQuad
          }
        }
      }
    }
  }
}

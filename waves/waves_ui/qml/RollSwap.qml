import QtQuick

// The hover controls' idle-to-live swap: one pill whose contents ride a
// short belt. The outgoing set leaves through the top exactly as the
// incoming arrives from the bottom, while the pill itself stretches
// between their two natural sizes and its fill and outline cross to the
// arriving control's, instead of each side appearing and vanishing on a
// bare `visible:` flip.
// Shape picked in scratchpad/pv_swap_lab.qml round 2 ("ROLL snap"): a
// 16px belt over 230ms with NO overlap, so the swap reads as a flip
// rather than a dissolve.
// The pill belongs to this wrapper, not to the two controls, which is why
// both load `bare`: mid-belt a control is half out of frame, and only a
// visible outline makes that read as sliding behind an edge instead of as
// something being clipped off.
// Gated on hoverMotion like RiseIn: with motion off the swap is instant.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.hoverMotion
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Item {
  id: rsw
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property real btnBorderW: 1.5
  readonly property int btnRad: 8              // button corner radius

  property bool live: false
  // Assigned inline by the call site; reparented into the pill so each
  // side can keep its own bindings and its own natural size.
  property Item idleItem: null
  property Item liveItem: null
  property color idleColor: "#d90d0f12"
  property color idleBorder: accentDim
  property color liveColor: idleColor
  property color liveBorder: idleBorder
  readonly property bool motion: host.hoverMotion
  readonly property real travel: 16
  // Centred horizontally by anchor, placed vertically by the belt below:
  // centerIn would own y and fight it.
  onIdleItemChanged: if (idleItem) {
    idleItem.parent = rswPill
    idleItem.anchors.horizontalCenter = rswPill.horizontalCenter
  }
  onLiveItemChanged: if (liveItem) {
    liveItem.parent = rswPill
    liveItem.anchors.horizontalCenter = rswPill.horizontalCenter
  }

  property real t: live ? 1 : 0
  Behavior on t {
    NumberAnimation {
      duration: rsw.motion ? 230 : 0
      easing.type: Easing.OutCubic
    }
  }
  // 0.44 is both the end of the exit and the start of the entry: no
  // overlap, so the two are never on screen together.
  readonly property real outFrac: 1 - Math.min(1, t / 0.44)
  readonly property real inFrac: Math.max(0, (t - 0.44) / 0.56)
  function _mix(a, b, k) {
    return Qt.rgba(a.r + (b.r - a.r) * k, a.g + (b.g - a.g) * k, a.b + (b.b - a.b) * k, a.a + (b.a - a.a) * k)
  }

  readonly property real wIdle: idleItem ? idleItem.width : 0
  readonly property real hIdle: idleItem ? idleItem.height : 0
  // The live side's size is LATCHED, not read raw. The state that ends
  // the live side usually also empties it in the same binding pass (a
  // stopped preview hides the scrubber, and its Column relayouts to 0
  // before t has moved), so reading the raw height collapsed the pill to
  // nothing in one frame instead of rolling the outgoing control away.
  // Holding the last real size keeps the roll on screen; a size change
  // WHILE live (a download joining a preview) eases instead of snapping.
  readonly property real _wLiveRaw: liveItem ? liveItem.width : 0
  readonly property real _hLiveRaw: liveItem ? liveItem.height : 0
  property real wLive: 0
  property real hLive: 0
  on_WLiveRawChanged: if (live || _wLiveRaw > 0)
    wLive = _wLiveRaw
  on_HLiveRawChanged: if (live || _hLiveRaw > 0)
    hLive = _hLiveRaw
  Behavior on wLive {
    enabled: rsw.live
    NumberAnimation {
      duration: rsw.motion ? 180 : 0
      easing.type: Easing.OutCubic
    }
  }
  Behavior on hLive {
    enabled: rsw.live
    NumberAnimation {
      duration: rsw.motion ? 180 : 0
      easing.type: Easing.OutCubic
    }
  }
  implicitWidth: wIdle + (wLive - wIdle) * t
  implicitHeight: hIdle + (hLive - hIdle) * t
  width: implicitWidth
  height: implicitHeight

  Rectangle {
    id: rswPill
    anchors.fill: parent
    radius: btnRad
    color: rsw._mix(rsw.idleColor, rsw.liveColor, rsw.t)
    border.width: btnBorderW
    border.color: rsw._mix(rsw.idleBorder, rsw.liveBorder, rsw.t)
    clip: true
    // The two contents are reparented in above; their belt offset and
    // presence are driven from here so neither call site repeats it.
    Binding {
      target: rsw.idleItem
      property: "opacity"
      value: rsw.outFrac
    }
    Binding {
      target: rsw.idleItem
      property: "visible"
      value: rsw.outFrac > 0.004
    }
    Binding {
      target: rsw.idleItem
      property: "y"
      value: (rswPill.height - rsw.hIdle) / 2 - rsw.travel * (1 - rsw.outFrac)
    }
    Binding {
      target: rsw.liveItem
      property: "opacity"
      value: rsw.inFrac
    }
    Binding {
      target: rsw.liveItem
      property: "visible"
      value: rsw.inFrac > 0.004
    }
    Binding {
      target: rsw.liveItem
      property: "y"
      value: (rswPill.height - rsw.hLive) / 2 + rsw.travel * (1 - rsw.inFrac)
    }
  }
}

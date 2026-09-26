import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import "primitives" as Primitives

// Track preview: the album art IS the play button. Idle it's just artwork;
// hover reveals a ▶ over a dark scrim; while previewing, a smooth arc
// hugging the art fills clockwise with playback position (⏸ over the scrim)
// and doubles as the seek surface: hovering the band around the art shows
// a ghost marker + time readout, click or drag seeks (a ghost cursor
// over a solid arc). Only the active track shows its ring,
// one shared player.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.artFxEase / host.artFxLift / host.artFxTilt / host.artFxVariant /
//   host.discDecode / host.fmtMs / host.previewDuration /
//   host.previewScrubbing / host.pvFrac / host.pvSt /
//   host.scrubPreviewVisual / host.seekPreview / host.termBlink /
//   host.togglePreview / host.warmArt
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Item {
  id: pa
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentContTx: "#86ffaa"   // text on accent container
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color accentSoft: "#9dffbe"   // CRT flash / phosphor highlight
  readonly property color bg: "#0d0f12"
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color surface3: "#1d2128"   // art bg / unlit meter / inset
  readonly property color surfaceHi: "#22262e"   // toast
  readonly property color textDim: "#6b6f78"

  property string url: ""
  property string kind: "track"
  property string pid: ""
  readonly property string st: pa.pid !== "" ? host.pvSt(pa.kind, pa.pid) : ""
  readonly property bool active: pa.st === "playing" || pa.st === "paused" || pa.st === "loading"
  readonly property real frac: host.pvFrac(pa.kind, pa.pid)
  property bool hovered: false
  // Show the play/pause glyph on hover, or while connecting/errored. Plain
  // playback shows through the ring alone, keeping the cover unobscured.
  readonly property bool showGlyph: pa.hovered || pa.st === "loading" || pa.st === "error"
  // Seek aim state: aimFrac is the track fraction under the mouse angle,
  // 12 o'clock = 0, clockwise (the arc's fill direction).
  property real aimFrac: 0
  function angFrac(mx, my) {
    var a = Math.atan2(my - height / 2, mx - width / 2)
    return ((a + Math.PI / 2) / (2 * Math.PI) + 1) % 1
  }
  implicitWidth: 48
  implicitHeight: 48
  // Same lazy-fetch latch as Art: rows hidden behind the search page's
  // first-5 cap must not spend a connection on a disc nobody can see.
  // Latches on first real show, never unloads after that.
  property bool everShown: false
  Component.onCompleted: if (visible)
    everShown = true
  onVisibleChanged: if (visible)
    everShown = true

  // The same four load states as Art, so the disc can say which one it is
  // in instead of showing one grey circle for all of them. Two
  // differences from Art, both deliberate:
  //   - "none" keys off url, not paImg.source: the retry below clears
  //     source and rebinds it, and a disc mid-retry is loading, not
  //     coverless.
  //   - "failed" waits for the retries to run out, otherwise the mark
  //     strobes red/green three times on the way there.
  readonly property string artState: pa.url === "" ? "none" : (paImg.status === Image.Error && paImg.retries >= 3) ? "failed" : paImg.status === Image.Ready ? "ready" : "loading"
  // Did this cover keep anyone waiting? A hit inside the grace window
  // shows no mark and does not fade, so a warm page never flickers.
  property bool artWaited: false
  onUrlChanged: artWaited = false
  Timer {
    interval: 250
    running: pa.artState === "loading" && pa.everShown
    onTriggered: pa.artWaited = true
  }

  // The same rest-armed hover tilt as Art (identical knobs, timings and
  // rest-before-tilt arming), so the track discs do not sit flat in
  // lists whose every other cover tilts. Held OFF while this disc's
  // preview is active: the
  // seek ring aims by pointer angle and needs a stable target.
  property real fxRx: 0
  property real fxRy: 0
  property real fxLift: 1.0
  readonly property bool fxOn: host.artFxVariant !== "none" && !pa.active
  property bool fxArmed: false
  function _fxAim(p) {
    var cx = width / 2, cy = height / 2
    fxRy = ((p.x - cx) / cx) * host.artFxTilt
    fxRx = -((p.y - cy) / cy) * host.artFxTilt
  }
  Timer {
    id: paFxArm
    interval: 90
    onTriggered: {
      if (!paFxHover.hovered)
        return
      pa.fxArmed = true
      pa.fxLift = host.artFxLift
      pa._fxAim(paFxHover.point.position)
    }
  }
  // A preview starting under an armed tilt (click) must not leave the
  // disc frozen mid-tilt while the ring takes over.
  onFxOnChanged: if (!fxOn) {
    paFxArm.stop()
    fxArmed = false
    fxRx = 0
    fxRy = 0
    fxLift = 1.0
  }
  Behavior on fxRx {
    NumberAnimation {
      duration: 280
      easing.type: host.artFxEase
    }
  }
  Behavior on fxRy {
    NumberAnimation {
      duration: 280
      easing.type: host.artFxEase
    }
  }
  Behavior on fxLift {
    NumberAnimation {
      duration: 280
      easing.type: host.artFxEase
    }
  }
  transform: [
    Rotation {
      origin.x: pa.width / 2
      origin.y: pa.height / 2
      axis: Qt.vector3d(1, 0, 0)
      angle: pa.fxRx
    },
    Rotation {
      origin.x: pa.width / 2
      origin.y: pa.height / 2
      axis: Qt.vector3d(0, 1, 0)
      angle: pa.fxRy
    },
    Scale {
      origin.x: pa.width / 2
      origin.y: pa.height / 2
      xScale: pa.fxLift
      yScale: pa.fxLift
    }
  ]
  HoverHandler {
    id: paFxHover
    enabled: pa.fxOn
    onHoveredChanged: {
      if (hovered)
        paFxArm.restart()
      else {
        paFxArm.stop()
        pa.fxArmed = false
        pa.fxRx = 0
        pa.fxRy = 0
        pa.fxLift = 1.0
      }
    }
    onPointChanged: if (pa.fxArmed)
      pa._fxAim(point.position)
  }

  // Circular cover. A Rectangle's clip ignores its radius (Qt draws children
  // to the square bounds), so the square crop is clipped to a real circle
  // with a MultiEffect mask (the same pattern the download grid uses above).
  // This rides Qt's Image lifecycle (async + cache + warm-pool + an
  // observable error state) instead of a hand-painted Canvas: the Canvas
  // had only a success signal and no retry, so any fetch that failed during
  // the search build's concurrent load burst left the disc grey forever, and
  // some rows lost that lottery at random. The progress ring and glyph are
  // separate siblings below and paint on top of this art.
  // The still plate under the cover: the disc's own background and, on it,
  // the same loading and failure marks every other cover in the app shows.
  // It sits outside coverWrap because coverWrap spins with the buffering
  // vinyl, and a spinning ">" is not a loading mark.
  Item {
    id: paPlate
    anchors.centerIn: parent
    width: 34
    height: 34   // artR * 2, matching coverWrap
    // Grey disc: the floor under everything, and all that shows once a
    // cover has landed.
    Rectangle {
      anchors.fill: parent
      radius: width / 2
      color: surface3
    }
    // Loading / failed mark, the compact form of the cover box's own
    // terminal face (see Art's artTerm) shaped into the circle.
    Rectangle {
      id: paTerm
      anchors.fill: parent
      radius: width / 2
      color: "#04140a"
      border.width: 1
      border.color: pa.artState === "failed" ? red : accentDim
      Behavior on border.color {
        ColorAnimation {
          duration: 350
        }
      }
      opacity: ((pa.artState === "loading" && pa.artWaited) || pa.artState === "failed") ? 1 : 0
      visible: opacity > 0
      Behavior on opacity {
        enabled: pa.artWaited
        NumberAnimation {
          duration: 300
          easing.type: Easing.InQuad
        }
      }
      // loading face: prompt + cursor
      Row {
        anchors.centerIn: parent
        spacing: 1
        opacity: pa.artState === "failed" ? 0 : 1
        Behavior on opacity {
          NumberAnimation {
            duration: 250
          }
        }
        Text {
          // Bigger prompt, slimmer cursor than the square box
          // uses: at 34px its ratios put a heavy block beside a
          // speck, and the pair has to read as a pair.
          textFormat: Text.PlainText
          text: ">"
          font.family: mono
          font.pixelSize: Math.max(1, Math.round(paPlate.width * 0.3))
          color: accent
        }
        Rectangle {
          width: paPlate.width * 0.12
          height: paPlate.width * 0.21
          anchors.verticalCenter: parent.verticalCenter
          color: accent
          // Shared blink (see host.termBlink). Gated on visible
          // first, so a settled disc's only dependency is
          // visible itself and it never reads the 20Hz tick.
          opacity: paTerm.visible ? host.termBlink : 1
        }
      }
      // failed face
      Text {
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: "x"
        font.family: mono
        font.pixelSize: Math.max(1, Math.round(paPlate.width * 0.38))
        color: red
        opacity: pa.artState === "failed" ? 1 : 0
        Behavior on opacity {
          NumberAnimation {
            duration: 250
          }
        }
      }
    }
    // No cover at all (a track whose album has none): say so, the way
    // Art does, instead of leaving a disc that reads as still loading.
    Text {
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: "≈"
      visible: pa.artState === "none"
      color: textDim
      font.family: mono
      font.pixelSize: paPlate.width * 0.4
    }
  }
  Item {
    id: coverWrap
    anchors.centerIn: parent
    width: 34
    height: 34   // artR * 2: a 34px circle centred in the 48px box
    rotation: paVinyl.rot   // buffering vinyl spins the cover itself
    // The cover fades in over the plate instead of popping. On
    // coverWrap, not on the Image: the Image is layered for the circle
    // mask, and animating opacity on a layered item re-renders its
    // texture every frame, times every disc on the page. coverWrap
    // holds only the cover and its (invisible) mask, so its opacity is
    // the cover's opacity.
    opacity: pa.artState === "ready" ? 1 : 0
    Behavior on opacity {
      enabled: pa.artWaited
      NumberAnimation {
        duration: 220
        easing.type: Easing.OutQuad
      }
    }
    Image {
      id: paImg
      anchors.fill: parent
      source: pa.everShown ? pa.url : ""
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
      cache: true
      visible: status === Image.Ready
      // Decode near display size (x2 for HiDPI crispness on the disc).
      sourceSize.width: host.discDecode
      sourceSize.height: host.discDecode
      // Pin decoded pixels in the warm pool so a rebuilt row (tab switch,
      // filter change, SHOW ALL) repaints without a re-decode. On a
      // transient error, re-request a bounded number of times (the Canvas
      // never did, hence the permanent grey): a cache/warm-pool hit makes
      // the retry instant. Qt.binding keeps the `source: pa.url` binding
      // alive across the reload so a later url change still propagates.
      property int retries: 0
      onStatusChanged: {
        if (status === Image.Ready)
          host.warmArt("" + source, sourceSize.width, sourceSize.height)
        else if (status === Image.Error && retries < 3)
          paRetry.restart()
      }
      Timer {
        id: paRetry
        interval: 600
        onTriggered: {
          paImg.retries += 1
          paImg.source = ""
          paImg.source = Qt.binding(function () {
            return pa.everShown ? pa.url : ""
          })
        }
      }
      Connections {
        target: pa
        function onUrlChanged() {
          paImg.retries = 0
        }
      }
      // Clip the square crop to a real circle: MultiEffect keeps only
      // what the white mask disc covers.
      layer.enabled: true
      layer.effect: MultiEffect {
        maskEnabled: true
        maskSource: ShaderEffectSource {
          sourceItem: paMask
          hideSource: false
        }
      }
    }
    Item {
      id: paMask
      anchors.fill: parent
      visible: false
      Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: "#ffffff"
      }
    }
  }
  // Playback ring: one continuous round-cap arc over a dim track, drawn
  // with the same CurveRenderer as the Ico glyphs so the curve is
  // genuinely smooth, no rotated-rectangle corners. Fills clockwise
  // from 12 o'clock.
  // Outer edge 19.5 + 1.6 stays within 22 of centre, so the ring can
  // never poke past the 44px thumb box and get clipped by neighbours.
  Item {
    id: ledRing
    visible: pa.active
    anchors.fill: parent
    readonly property real ringR: 19.5
    // Aim UI waits for the pointer to REST over the band (or a press):
    // the straight path to the disc's play/pause crosses the ring, and
    // the readout flashing on every pass-through reads as jarring.
    // Scrubbing always aims instantly.
    readonly property bool aiming: (paZone.ringHover && paZone.aimArmed) || paZone.scrubbing
    Shape {
      anchors.fill: parent
      antialiasing: true
      preferredRendererType: Shape.CurveRenderer
      // dim track (full circle)
      ShapePath {
        strokeColor: "#293dff6e"
        strokeWidth: 3.2
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        PathAngleArc {
          centerX: ledRing.width / 2
          centerY: ledRing.height / 2
          radiusX: ledRing.ringR
          radiusY: ledRing.ringR
          startAngle: -90
          sweepAngle: 360
        }
      }
      // lit arc (parked at zero while the buffering vinyl settles)
      ShapePath {
        strokeColor: accent
        strokeWidth: 3.2
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        PathAngleArc {
          centerX: ledRing.width / 2
          centerY: ledRing.height / 2
          radiusX: ledRing.ringR
          radiusY: ledRing.ringR
          startAngle: -90
          sweepAngle: paVinyl.busy ? 0 : 360 * Math.max(0, Math.min(1, pa.frac))
        }
      }
    }
    // Buffering vinyl: while the stream resolves, the cover itself spins
    // up like a record, accelerating through
    // the first turn then cruising, while the ring stays calm. The
    // moment the song is ready the disc eases to rest at its original
    // orientation (always completing the current turn forward) and
    // the playhead sparks in at 12 o'clock, where the progress arc
    // then rises. Smooth and continuous by design: no dots, no segments.
    Item {
      id: paVinyl
      anchors.fill: parent
      readonly property bool loadingNow: pa.st === "loading"
      property bool settling: false
      readonly property bool busy: loadingNow || settling
      property real rot: 0
      onLoadingNowChanged: {
        if (loadingNow) {
          vinylSettle.stop()
          settling = false
          rot = 0
          vinylSpin.restart()
        } else if (pa.st === "playing" || pa.st === "paused") {
          vinylSpin.stop()
          settling = true
          vinylSettle.restart()
        } else {
          vinylSpin.stop()
          settling = false
          rot = 0
        }
      }
      SequentialAnimation {
        id: vinylSpin
        // spin-up through the first turn, then a steady cruise;
        // the long tail outlasts any realistic load (4+ minutes)
        NumberAnimation {
          target: paVinyl
          property: "rot"
          from: 0
          to: 360
          duration: 1300
          easing.type: Easing.InQuad
        }
        NumberAnimation {
          target: paVinyl
          property: "rot"
          from: 360
          to: 360 * 400
          duration: 400 * 650
        }
      }
      Rectangle {
        id: vinylSpark
        x: ledRing.width / 2 - width / 2
        y: ledRing.height / 2 - ledRing.ringR - height / 2
        width: 5
        height: 5
        radius: 2.5
        color: accentSoft
        antialiasing: true
        opacity: 0
      }
      SequentialAnimation {
        id: vinylSparkPop
        ParallelAnimation {
          NumberAnimation {
            target: vinylSpark
            property: "opacity"
            from: 0
            to: 1
            duration: 110
          }
          NumberAnimation {
            target: vinylSpark
            property: "scale"
            from: 2.2
            to: 1
            duration: 260
            easing.type: Easing.OutBack
          }
        }
        NumberAnimation {
          target: vinylSpark
          property: "opacity"
          to: 0
          duration: 200
        }
      }
      SequentialAnimation {
        id: vinylSettle
        // The settle target is snapshotted here, not bound on the
        // NumberAnimation: a `to:` binding reading `rot` re-evaluates
        // on every frame the animation itself writes, which is one
        // easing overshoot away from a ratcheting runaway.
        ScriptAction {
          script: {
            vinylSparkPop.restart()
            vinylSettleAnim.to = Math.ceil(paVinyl.rot / 360) * 360
          }
        }
        NumberAnimation {
          id: vinylSettleAnim
          target: paVinyl
          property: "rot"
          duration: 520
          easing.type: Easing.OutCubic
        }
        ScriptAction {
          script: {
            paVinyl.rot = 0
            paVinyl.settling = false
          }
        }
      }
    }
    // Ghost cursor: a marker dot at the aim angle, bright
    // phosphor over the unplayed side, a dark notch punched into the
    // arc over the played side, so it stands out on both sides of
    // the playhead.
    Rectangle {
      opacity: ledRing.aiming ? 1 : 0
      visible: opacity > 0
      Behavior on opacity {
        NumberAnimation {
          duration: 110
        }
      }
      readonly property real ang: -Math.PI / 2 + pa.aimFrac * 2 * Math.PI
      readonly property bool played: pa.aimFrac <= pa.frac
      antialiasing: true
      x: ledRing.width / 2 + ledRing.ringR * Math.cos(ang) - width / 2
      y: ledRing.height / 2 + ledRing.ringR * Math.sin(ang) - height / 2
      width: 6
      height: 6
      radius: 3
      color: played ? bg : accentSoft
      border.width: played ? 1 : 0
      border.color: accentDim
    }
  }
  // Only a whisper of a scrim, and only when the glyph is up.
  Rectangle {
    anchors.centerIn: parent
    width: 34
    height: 34
    radius: 17
    color: "#000000"
    opacity: pa.showGlyph ? 0.34 : 0
    Behavior on opacity {
      NumberAnimation {
        duration: 150
      }
    }
  }
  Item {
    anchors.centerIn: parent
    width: 30
    height: 30
    // The glyph eases in and out with the scrim (fade plus a slight
    // settle) instead of popping with the hover flag.
    opacity: pa.showGlyph ? 1 : 0
    scale: pa.showGlyph ? 1 : 0.8
    visible: opacity > 0
    Behavior on opacity {
      NumberAnimation {
        duration: 150
      }
    }
    Behavior on scale {
      NumberAnimation {
        duration: 190
        easing.type: Easing.OutCubic
      }
    }
    // Play/pause/error as a vector glyph. Loading shows no glyph:
    // the buffering animation (paVinyl spins the cover) is the activity
    // indicator, over the lightly scrimmed art. A soft dark disc
    // behind the glyph gives the same legibility over art a
    // Text.Outline would.
    Item {
      anchors.fill: parent
      opacity: pa.st !== "loading" ? 1 : 0
      visible: opacity > 0
      Behavior on opacity {
        NumberAnimation {
          duration: 150
        }
      }
      Rectangle {
        anchors.centerIn: parent
        width: 26
        height: 26
        radius: 13
        color: "#55000000"
      }
      Ico {
        anchors.centerIn: parent
        name: pa.st === "playing" ? "pause" : (pa.st === "error" ? "close" : "play")
        color: pa.st === "error" ? red : accent
        size: 17
      }
    }
  }
  // The would-seek time, floating above the art while aiming at the ring.
  Rectangle {
    opacity: ledRing.aiming ? 1 : 0
    visible: opacity > 0
    Behavior on opacity {
      NumberAnimation {
        duration: 120
      }
    }
    anchors.horizontalCenter: parent.horizontalCenter
    y: -18
    width: paAimTxt.implicitWidth + 12
    height: 16
    radius: 4
    color: surfaceHi
    border.color: border1
    Text {
      id: paAimTxt
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: host.fmtMs(pa.aimFrac * host.previewDuration)
      color: accentContTx
      font.family: mono
      font.pixelSize: 9
    }
  }
  // Pointer zone (ghost cursor). Idle, the whole box starts the
  // preview. While this track
  // is active, the disc toggles play/pause and the band around it is the
  // seek surface: a resting hover aims the ghost marker, press/drag scrubs the
  // fill locally, the single real seek fires on release (same discipline
  // as the PreviewBar scrubber, no mid-gesture flush pop).
  MouseArea {
    id: paZone
    anchors.fill: parent
    anchors.margins: -6
    hoverEnabled: true
    preventStealing: true
    property bool scrubbing: false
    property bool ringHover: false
    // Rest-armed aim (same idiom as the art tilt): the readout and
    // ghost marker appear only once the pointer stops moving over the
    // band, so crossing the ring on the way to play/pause never
    // flashes them. The arm timer restarts on every move while
    // unarmed; a press (scrub) bypasses arming entirely.
    property bool aimArmed: false
    onRingHoverChanged: if (!ringHover) {
      paAimArm.stop()
      aimArmed = false
    }
    Timer {
      id: paAimArm
      interval: 160
      onTriggered: paZone.aimArmed = true
    }
    readonly property real discR: 17
    readonly property real bandR: 28
    readonly property real idleR: 24
    function dist(mx, my) {
      var dx = mx - width / 2
      var dy = my - height / 2
      return Math.sqrt(dx * dx + dy * dy)
    }
    cursorShape: (ringHover || dist(mouseX, mouseY) <= (pa.active ? discR : idleR)) ? Qt.PointingHandCursor : Qt.ArrowCursor
    onPositionChanged: function (m) {
      var d = dist(m.x, m.y)
      pa.hovered = pa.active ? d <= discR : d <= idleR
      ringHover = pa.active && d > discR && d <= bandR
      if (ringHover && !aimArmed)
        paAimArm.restart()
      if (ringHover || scrubbing) {
        pa.aimFrac = pa.angFrac(m.x + x, m.y + y)
        if (scrubbing)
          host.scrubPreviewVisual(pa.aimFrac)
      }
    }
    onEntered: pa.hovered = !pa.active
    onExited: {
      pa.hovered = false
      ringHover = false
    }
    onPressed: function (m) {
      var d = dist(m.x, m.y)
      if (pa.active && d > discR && d <= bandR) {
        scrubbing = true
        host.previewScrubbing = true
        pa.aimFrac = pa.angFrac(m.x + x, m.y + y)
        host.scrubPreviewVisual(pa.aimFrac)
        m.accepted = true
      } else if (d <= (pa.active ? discR : idleR)) {
        m.accepted = true
      } else {
        m.accepted = false
      }
    }
    onReleased: function (m) {
      if (scrubbing) {
        scrubbing = false
        host.previewScrubbing = false
        host.seekPreview(pa.aimFrac)
      } else if (dist(m.x, m.y) <= (pa.active ? discR : idleR)) {
        host.togglePreview(pa.kind, pa.pid, 0)
      }
    }
    onCanceled: {
      scrubbing = false
      host.previewScrubbing = false
    }
  }
}

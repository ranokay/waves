import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import "primitives" as Primitives

// Square cover box: the app's one artwork surface. Decodes once at a
// fixed size, paints a caller-supplied stand-in beneath the cover while
// it loads, shows the “art: GET” terminal placeholder for waits, and
// carries the opt-in hover tilt and the playing-raise effects.
// 'host' is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load. The cover reads through it:
//   host.artFxVariant  the “Cover art tilts on hover” setting (tilt/none)
//   host.artFxTilt / host.artFxLift / host.artFxEase  the tilt knobs
//   host.artPlayLift / host.artPlayShadowY / host.artPlayShadowBlur /
//     host.artPlayShadowA / host.artPlayBreath / host.artPlayBreathMs
//     the resting-raise knobs
//   host.pvSt(kind, id)  the shared preview state a raised cover follows
//   host.warmArt(url, w, h)  pin a decoded cover in the warm pool
//   host.onScreen  pause the loading blink while the window is away
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: artRoot
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentContTx: "#86ffaa"   // text on accent container
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color surface3: "#1d2128"   // art bg / unlit meter / inset
  readonly property color textDim: "#6b6f78"
  property string url: ""
  // Optional stand-in painted BENEATH the cover: a smaller copy the
  // caller already has on screen (the clicked card's thumbnail). It
  // shows the frame this Art is shown, the full cover then fades in
  // over it, and neither the grey box nor the "art: GET" placeholder
  // ever appears while a stand-in is up. When it is the very same URL
  // as `url` (the usual case, the page hero asks for the card size)
  // the two share one decoded pixmap and the cover is simply there.
  property string underUrl: ""
  readonly property bool underReady: underUrl !== "" && underImg.status === Image.Ready
  // "loading" while the fetch is in flight, "failed" on a load error
  // (e.g. network down), "ready" once decoded, "none" when there is no
  // art URL at all (keeps the neutral ♪, absence isn't an error).
  readonly property string artState: url === "" ? "none" : artImg.status === Image.Error ? "failed" : artImg.status === Image.Ready ? "ready" : "loading"
  // Set only when a load has been in flight past the grace timer below:
  // warm-pool cache hits and sub-perceptual reloads (delegate rebuilds,
  // sourceSize settling during layout) must keep painting instantly,
  // the placeholder and fade-in are only for covers that made us wait.
  property bool artWaited: false
  // Recycled delegates keep component state, a new cover starts its
  // own grace window instead of inheriting the previous one's verdict.
  onUrlChanged: artWaited = false
  // Never fetch a cover the user has never been shown. Rows hidden
  // behind a section cap (search's first-5) still instantiate, and
  // their fetches would otherwise queue ahead of the on-screen art on
  // the six shared connections, leaving visible covers hanging while
  // invisible ones download. `visible` here reads EFFECTIVE
  // visibility (ancestors included), so the latch flips the first time
  // the element is actually shown and the fetch starts then. Once
  // latched it never drops: a tab switch or filter change must keep
  // repainting instantly from the cache, never unload.
  property bool everShown: false
  onVisibleChanged: if (visible)
    everShown = true
  Timer {
    interval: 250
    // everShown gates the fetch itself (below), so a hidden row is
    // not "waiting" yet; its grace window starts when it first shows.
    running: artRoot.artState === "loading" && artRoot.everShown
    onTriggered: artRoot.artWaited = true
  }
  // Fixed decode size for the cover. The art is only for viewing, so it is
  // decoded ONCE at (roughly) its first display size and then just scaled to
  // fit. Binding the decode size to the live element width made a window
  // resize re-request the Image on every step, and since opacity follows the
  // load state (below) that blinked the cover to the grey placeholder. With a
  // fixed size a resize never touches the Image, so it simply stays put.
  // Seeded at first layout; ×2 keeps it crisp on HiDPI screens.
  property int decodeW: 96
  property bool _decodeSeeded: false
  function _seedDecode() {
    if (!_decodeSeeded && width > 0) {
      _decodeSeeded = true
      decodeW = Math.round(width * 2)
    }
  }
  onWidthChanged: _seedDecode()
  Component.onCompleted: {
    _seedDecode()
    if (visible)
      everShown = true
  }
  color: surface3
  radius: 6
  border.color: border1
  border.width: 1
  clip: true
  // Album-art hover tilt (from BGT's CoverArt.qml): opt-in per call
  // site. The whole cover (art, border, anything anchored on it)
  // tilts toward the cursor and lifts slightly, springing back on
  // exit. Pure render-thread transforms: Image geometry, decode size
  // and clip untouched, so hoverFx: false sites are pixel-identical
  // and cost nothing.
  property bool hoverFx: false
  readonly property string fxVariant: host.artFxVariant
  property real fxRx: 0
  property real fxRy: 0
  property real fxLift: 1.0
  property real fxGlossX: width / 2
  property real fxGlossY: height / 2
  // What this cover IS, so the resting raise can follow the shared
  // player. The call site declares it; sites that leave fxId empty stay
  // inert: every binding below folds away.
  // Matching is literal (this cover's own preview), the same rule
  // pvActive already applies everywhere else: a cover that lifts without
  // being asked reads as a glitch, and one album can sit on three
  // shelves at once.
  property string fxKind: ""
  property string fxId: ""
  // Gated on the same Settings switch as the tilt: "Cover art tilts on
  // hover" is the app's only "artwork moves" control, and someone who
  // turned motion off should not be handed new motion.
  readonly property string fxPlaySt: (hoverFx && fxVariant !== "none" && fxId !== "") ? host.pvSt(fxKind, fxId) : ""
  // Same three live states PreviewArt calls "active"; "error" is a
  // transient flash, not something to raise the cover for.
  readonly property bool fxPlayRaised: fxPlaySt === "playing" || fxPlaySt === "paused" || fxPlaySt === "loading"
  // A preview usually ends with the pointer still on the cover, on the
  // very button that stopped it. Dropping there is wrong twice over: the
  // cover is still being pointed at, so it has no business lying flat,
  // and the hover tilt would take it straight back up, which reads as
  // the drop bouncing. So it stays up, and comes down when the pointer
  // leaves: one movement, and the pointer is gone before it starts.
  property bool fxHoldRaise: false
  onFxPlayRaisedChanged: fxHoldRaise = fxPlayRaised ? false : fxHover.hovered
  readonly property bool fxRaised: fxPlayRaised || fxHoldRaise
  readonly property bool fxPaused: fxPlaySt === "paused"
  // `&& !fxRaised` is the whole "stop tilting" half of this: the
  // onFxOnChanged handler below already lays a mid-tilt cover flat when
  // this goes false, which is exactly the hand-off from tilt to raise.
  readonly property bool fxOn: hoverFx && fxVariant !== "none" && !fxRaised
  // The effect waits for the pointer to REST on the cover. A scrolling
  // list slides its rows under a stationary cursor, and arming every
  // row that passes under it would fire dozens of 280 ms lift and tilt
  // springs at once (and, on tilt_shadow, a layer FBO per row), for
  // covers nobody pointed at, a major source of playlist scroll jank.
  // 90 ms of unbroken hover is below notice when you
  // mean it, and far longer than a row spends under the cursor
  // mid-scroll. Disarms the instant the pointer leaves, so springing
  // back is never delayed.
  property bool fxArmed: false
  readonly property bool fxHovering: fxOn && fxArmed && fxHover.hovered
  function _fxAim(p) {
    var cx = width / 2, cy = height / 2
    fxRy = ((p.x - cx) / cx) * host.artFxTilt
    fxRx = -((p.y - cy) / cy) * host.artFxTilt
    fxGlossX = p.x
    fxGlossY = p.y
  }
  Timer {
    id: fxArm
    interval: 90
    // Take the lift AND the current aim on arming: a cursor that
    // lands and holds still must tilt without needing a nudge.
    onTriggered: {
      if (!fxHover.hovered || !artRoot.fxOn)
        return
      artRoot.fxArmed = true
      artRoot.fxLift = host.artFxLift
      artRoot._fxAim(fxHover.point.position)
    }
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
  // Turning the effect off in Settings while a cover is mid-tilt must
  // lay it flat, not freeze it there (the same guard the track discs
  // carry for a preview starting under an armed tilt).
  onFxOnChanged: if (!fxOn) {
    fxArm.stop()
    fxArmed = false
    fxRx = 0
    fxRy = 0
    fxLift = 1.0
  }
  // ONE dial for "raised", 0 to 1. The resting swell and the shadow's
  // shape both read it, so they cannot drift apart mid-transition: the
  // card rises and its shadow settles under it on the same curve, in
  // the same 260 ms. Its own value, never the hover lift's, which snaps
  // back to 1.0 on every pointer exit. Eases, never springs: OutBack
  // overshoots, and a cover meant to settle and stay must not bounce.
  property real fxRaiseT: fxRaised ? 1 : 0
  Behavior on fxRaiseT {
    NumberAnimation {
      duration: 260
      easing.type: Easing.OutCubic
    }
  }
  readonly property real fxRaiseScale: 1 + (host.artPlayLift - 1) * fxRaiseT
  // How present the shadow is, 0 to 1. Hovering casts one too, so a
  // cover that starts playing under the pointer deepens a shadow that
  // is already there. Animated rather than switched, and layer.enabled
  // follows it, so the layer comes up while the shadow is still
  // invisible and goes away only after it has faded out.
  property real fxShadow: (fxRaised || fxHovering) ? 1 : 0
  Behavior on fxShadow {
    NumberAnimation {
      duration: 260
      easing.type: Easing.OutCubic
    }
  }
  // Paused: a slow, shallow breath, not a dimmed shadow. 0 = full depth,
  // 1 = the bottom of the exhale.
  property real fxBreath: 0
  SequentialAnimation {
    running: artRoot.fxPaused
    loops: Animation.Infinite
    NumberAnimation {
      target: artRoot
      property: "fxBreath"
      to: 1
      duration: host.artPlayBreathMs
      easing.type: Easing.InOutSine
    }
    NumberAnimation {
      target: artRoot
      property: "fxBreath"
      to: 0
      duration: host.artPlayBreathMs
      easing.type: Easing.InOutSine
    }
  }
  // Resuming stops the loop wherever it happens to be; the amplitude is
  // shallow enough that settling back to full depth is not a visible step.
  onFxPausedChanged: if (!fxPaused)
    fxBreath = 0
  readonly property real fxBreathK: 1 - host.artPlayBreath * fxBreath
  readonly property real fxShadowDepth: fxShadow * fxBreathK
  // A raised cover sits above its neighbours, so neither the swell nor
  // the shadow is sliced by the next sibling's background.
  // Held for the whole descent, not just while raised: dropping back
  // behind the next sibling's background at the instant the preview ends
  // clips the last of the swell and the shadow, which reads as a snap.
  // Keyed on shadow depth, not on the raise: a merely hovered cover
  // casts a shadow too, and at z 0 the next sibling's background paints
  // over it, so the hover shadow never showed until preview raised the
  // card.
  z: (fxRaiseT > 0.001 || fxShadowDepth > 0.004) ? 1 : 0
  transform: [
    Rotation {
      origin.x: artRoot.width / 2
      origin.y: artRoot.height / 2
      axis: Qt.vector3d(1, 0, 0)
      angle: artRoot.fxRx
    },
    Rotation {
      origin.x: artRoot.width / 2
      origin.y: artRoot.height / 2
      axis: Qt.vector3d(0, 1, 0)
      angle: artRoot.fxRy
    },
    Scale {
      origin.x: artRoot.width / 2
      origin.y: artRoot.height / 2
      xScale: artRoot.fxLift
      yScale: artRoot.fxLift
    },
    Scale {
      origin.x: artRoot.width / 2
      origin.y: artRoot.height / 2
      xScale: artRoot.fxRaiseScale
      yScale: artRoot.fxRaiseScale
    }
  ]
  // HoverHandler, not a MouseArea: call sites' own MouseAreas (open
  // the page, hover controls) keep every click and hover.
  HoverHandler {
    id: fxHover
    // Stays enabled through the raise, where the tilt is off: something
    // has to know the pointer is still on the cover when the preview
    // ends. fxOn gates the movement instead, below.
    enabled: artRoot.hoverFx && artRoot.fxVariant !== "none"
    onHoveredChanged: {
      if (hovered)
        fxArm.restart()
      else {
        fxArm.stop()
        artRoot.fxArmed = false
        artRoot.fxHoldRaise = false
        artRoot.fxRx = 0
        artRoot.fxRy = 0
        artRoot.fxLift = 1.0
      }
    }
    // fxArmed implies hovered and fxOn (both clear it), so this is the
    // whole guard: an unarmed pass-through moves nothing.
    onPointChanged: if (artRoot.fxArmed)
      artRoot._fxAim(point.position)
  }
  Image {
    // The stand-in (see underUrl). Declared before artImg so it paints
    // beneath; gone once the cover above it is fully opaque.
    id: underImg
    anchors.fill: parent
    source: artRoot.everShown ? artRoot.underUrl : ""
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
    cache: true
    visible: status === Image.Ready && artImg.opacity < 1
    // Same decode size as the cover: one pool key, one pixmap when
    // the URLs coincide.
    sourceSize.width: artRoot.decodeW
    sourceSize.height: artRoot.decodeW
    onStatusChanged: if (status === Image.Ready)
      host.warmArt("" + source, sourceSize.width, sourceSize.height)
  }
  Image {
    id: artImg
    anchors.fill: parent
    source: artRoot.everShown ? artRoot.url : ""
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
    cache: true
    // Art fades in over the placeholder instead of popping.
    opacity: artRoot.artState === "ready" ? 1 : 0
    visible: opacity > 0
    Behavior on opacity {
      enabled: artRoot.artWaited
      NumberAnimation {
        duration: 220
        easing.type: Easing.OutQuad
      }
    }
    // Decode at (roughly) display resolution instead of the full 320-480px
    // source (each tiny thumbnail would otherwise keep a full-size bitmap and
    // burn decode time). Art is square, so one decode dimension covers both,
    // and decodeW is fixed once (see above) so a resize never re-requests it.
    sourceSize.width: artRoot.decodeW
    sourceSize.height: artRoot.decodeW
    // Pin this cover's decoded pixels in the warm pool so the next
    // page that shows it (or a revisit) paints without a re-decode.
    onStatusChanged: if (status === Image.Ready)
      host.warmArt("" + source, sourceSize.width, sourceSize.height)
  }
  Text {
    anchors.centerIn: parent
    // A stand-in on its way (url still empty while the page payload
    // is in flight) must not flash the no-art glyph first.
    visible: artRoot.artState === "none" && artRoot.underUrl === ""
    text: "≈"
    color: textDim
    font.family: mono
    font.pixelSize: parent.width * 0.4
  }
  // Terminal-fetch placeholder: a CRT box showing "art: GET" with a
  // blinking cursor while loading, cross-fading to "art: ERR / no link"
  // on failure, and fading out underneath the cover as it arrives.
  Rectangle {
    id: artTerm
    anchors.fill: parent
    radius: artRoot.radius
    color: "#04140a"
    border.width: 1
    border.color: artRoot.artState === "failed" ? red : accentDim
    Behavior on border.color {
      ColorAnimation {
        duration: 350
      }
    }
    // Loading face waits out the grace timer so quick loads (cache
    // hits, delegate rebuilds on page revisits) never flash the box;
    // a hard failure shows immediately.
    // A visible stand-in is never "waiting" (and a failed full cover
    // over a good stand-in stays silent): the box only ever covers
    // an empty frame.
    opacity: (!artRoot.underReady && ((artRoot.artState === "loading" && artRoot.artWaited) || artRoot.artState === "failed")) ? 1 : 0
    visible: opacity > 0
    Behavior on opacity {
      enabled: artRoot.artWaited
      NumberAnimation {
        duration: 300
        easing.type: Easing.InQuad
      }
    }
    // Below this the "art: GET / ERR" labels are unreadable, collapse
    // to the bare prompt (loading) / a red x (failed).
    readonly property bool compact: width < 64
    // loading face
    Column {
      anchors.centerIn: parent
      spacing: 4
      opacity: artRoot.artState === "failed" ? 0 : 1
      Behavior on opacity {
        NumberAnimation {
          duration: 250
        }
      }
      Text {
        visible: !artTerm.compact
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: "art: GET"
        font.family: mono
        font.pixelSize: Math.max(1, Math.round(artTerm.width * 0.11))
        color: accentContTx
      }
      Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 2
        Text {
          textFormat: Text.PlainText
          text: ">"
          font.family: mono
          font.pixelSize: Math.max(1, Math.round(artTerm.width * (artTerm.compact ? 0.22 : 0.11)))
          color: accent
        }
        Rectangle {
          width: artTerm.width * (artTerm.compact ? 0.16 : 0.08)
          height: artTerm.width * (artTerm.compact ? 0.26 : 0.13)
          anchors.verticalCenter: parent.verticalCenter
          color: accent
          SequentialAnimation on opacity {
            // Pause the blink when hidden or unfocused, same
            // reasoning as the WaveMark parallax scroll.
            running: artRoot.artState === "loading" && artTerm.visible && host.onScreen
            loops: Animation.Infinite
            NumberAnimation {
              from: 1
              to: 0
              duration: 60
            }
            PauseAnimation {
              duration: 420
            }
            NumberAnimation {
              from: 0
              to: 1
              duration: 60
            }
            PauseAnimation {
              duration: 420
            }
          }
        }
      }
    }
    // failed face
    Column {
      anchors.centerIn: parent
      spacing: 4
      opacity: artRoot.artState === "failed" ? 1 : 0
      Behavior on opacity {
        NumberAnimation {
          duration: 250
        }
      }
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: artTerm.compact ? "x" : "art: ERR"
        font.family: mono
        font.pixelSize: Math.max(1, Math.round(artTerm.width * (artTerm.compact ? 0.30 : 0.11)))
        font.bold: artTerm.compact
        color: red
      }
      Text {
        visible: !artTerm.compact
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: "no link"
        font.family: mono
        font.pixelSize: Math.max(1, Math.round(artTerm.width * 0.11))
        color: textDim
      }
    }
  }
  // Gloss variant (from BGT): a cursor-following radial highlight.
  // Behind a Loader: the Shape + gradient exist only for tilt_gloss
  // instances, every other Art (there are hundreds in list delegates)
  // creates nothing here.
  Loader {
    anchors.fill: parent
    z: 10   // above any call-site children riding the art
    active: artRoot.hoverFx && artRoot.fxVariant === "tilt_gloss"
    sourceComponent: Item {
      clip: true
      opacity: artRoot.fxHovering ? 1 : 0
      Behavior on opacity {
        NumberAnimation {
          duration: 140
        }
      }
      Shape {
        anchors.fill: parent
        antialiasing: true
        ShapePath {
          strokeColor: "transparent"
          fillGradient: RadialGradient {
            centerX: artRoot.fxGlossX
            centerY: artRoot.fxGlossY
            centerRadius: Math.max(artRoot.width, artRoot.height) * 0.55
            focalX: artRoot.fxGlossX
            focalY: artRoot.fxGlossY
            GradientStop {
              position: 0.0
              color: Qt.rgba(1, 1, 1, 0.42)
            }
            GradientStop {
              position: 0.45
              color: Qt.rgba(1, 1, 1, 0.0)
            }
          }
          startX: 0
          startY: 0
          PathLine {
            x: artRoot.width
            y: 0
          }
          PathLine {
            x: artRoot.width
            y: artRoot.height
          }
          PathLine {
            x: 0
            y: artRoot.height
          }
          PathLine {
            x: 0
            y: 0
          }
        }
      }
    }
  }
  // Offset depth shadow (BGT tilt_shadow: sx=-px*14, sy=-py*14+6). While
  // hovered it leans away from the tilt; while raised it sits straight
  // down at artPlayShadowY, and fxRaiseT crosses between the two, so the
  // shadow never jumps as a hovered cover becomes a playing one. Gated
  // on fxShadowDepth, not on a state boolean: the layer exists slightly
  // before and after the shadow is visible, which is what makes the fade
  // seamless. Idle covers still never pay the layer FBO, and the 90 ms
  // rest-arming means a scrolling list cannot mint one per row.
  layer.enabled: artRoot.fxShadowDepth > 0.004
  layer.effect: MultiEffect {
    shadowEnabled: true
    shadowColor: Qt.rgba(0, 0, 0, host.artPlayShadowA * artRoot.fxShadowDepth)
    shadowBlur: host.artPlayShadowBlur
    shadowHorizontalOffset: -(artRoot.fxRy / host.artFxTilt) * 14 * (1 - artRoot.fxRaiseT)
    shadowVerticalOffset: ((artRoot.fxRx / host.artFxTilt) * 14 + 6) * (1 - artRoot.fxRaiseT) + host.artPlayShadowY * artRoot.fxRaiseT * artRoot.fxBreathK
  }
}

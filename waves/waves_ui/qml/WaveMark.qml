import QtQuick

// ASCII ocean-wave logo (the "Parallax Ocean" mark):
// six depth layers of wave glyphs - foam specks, small ripples, rolling swell,
// and a big foreground crest - all scrolling left at parallax speeds (back layers
// slower) for moving-water depth, rather than flat parallel lines.
// `host` is Main.qml's root object, bound at its single instantiation
// (the header's logo mark) and required so a missed binding fails at load.
// It reads through it:
//   host.onScreen / host.presentFresh
// Split out of Main.qml (#315 slice 9). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Rectangle {
  id: wm
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentContTx: "#86ffaa"   // text on accent container
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color green: "#3ef08a"   // LOSSLESS tier + done state
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)

  property int boxW: 133                        // width
  property int boxH: 34
  readonly property real uscale: boxH / 34      // glyph px reference = box height
  // Front-layer scroll speed (px/sec); back layers scale by their parallax factor.
  // 46 px/s baseline x 0.21 ~= 9.66 px/s - calm.
  // One shared loop clock (0..1 over loopSecs); each layer derives its own
  // offset as (t x k + phase) tiles, the exact math of the README banner GIF
  // (96 frames @ 14 fps), so box and banner show the same water.
  property real loopSecs: 96 / 14
  property real t: 0
  // Idle-lightning clock: its own slow loop (the storyboard below spans
  // 20s, longer than the water's ~6.9s loop, so strikes drift across
  // different wave positions instead of always hitting the same crest).
  readonly property real idleLoopSecs: 20
  property real idleT: 0
  Timer {
    // Pause while the window is off screen (hidden/minimised). Focus
    // is deliberately NOT part of the gate: an unfocused window is
    // still on screen, and the water freezing on every focus change
    // looked like a rendering glitch (livetest report).
    running: wm.visible && host.onScreen
    interval: 50
    repeat: true                // 20 Hz step (see delegate note)
    onTriggered: {
      if (!host.presentFresh())
        // no step while unpresented (see the LED clock)
        return
      wm.t = (wm.t + 0.05 / wm.loopSecs) % 1
      wm.idleT = (wm.idleT + 0.05 / wm.idleLoopSecs) % 1
    }
  }
  property bool storm: false                    // hover -> ascii lightning strikes
  // Content is clipped by an inner item inset past the rounded corners, so a
  // glyph (or bolt) can never poke out a corner, a clip on the rounded
  // Rectangle itself is rectangular and leaves the corner triangles exposed.
  readonly property int inset: 3
  width: boxW
  height: boxH
  radius: 8
  color: "#04140a"
  border.color: accentDim
  border.width: 1

  Item {
    id: wmClip
    anchors.fill: parent
    anchors.margins: wm.inset
    clip: true

    // Six-layer water lifted verbatim from the README banner GIF generator
    // (make_logo_gif.py): faint foam up top fading into brighter, denser
    // swell. k = pattern-tiles travelled per loop (parallax: front faster);
    // ph = initial offset (0..1 of a tile) so crests don't line up. px is
    // the GIF's glyph size normalised to the 34px box reference.
    Repeater {
      model: [
        {
          yf: 0.05,
          px: 3.5,
          op: 0.34,
          k: 1,
          ph: 0.00,
          pat: "   '    .     *   :   .   ",
          col: accentContTx
        },
        {
          yf: 0.18,
          px: 4.0,
          op: 0.46,
          k: 1,
          ph: 0.42,
          pat: ".~-~..-~-.~..-~-.",
          col: green
        },
        {
          yf: 0.31,
          px: 4.0,
          op: 0.56,
          k: 2,
          ph: 0.75,
          pat: "-.~-..~.-~-..~.-",
          col: green
        },
        {
          yf: 0.45,
          px: 5.0,
          op: 0.70,
          k: 2,
          ph: 0.18,
          pat: "_.-~-._.,-~-._.-",
          col: accent
        },
        {
          yf: 0.59,
          px: 5.5,
          op: 0.84,
          k: 3,
          ph: 0.60,
          pat: ".-~^-._,.~-^._.-~",
          col: accent
        },
        {
          yf: 0.72,
          px: 6.5,
          op: 1.00,
          k: 3,
          ph: 0.10,
          pat: "_.-~^~-._.~^'~._",
          col: accent
        }
      ]
      delegate: Row {
        required property var modelData
        readonly property int reps: 9
        // One pattern-tile's width, NOT the full repeated strip: the
        // (t x k + ph) fraction is in units of a single tile, exactly as
        // in the GIF generator, so the drift speed matches the README.
        readonly property real tileW: tile.width / reps
        y: Math.round(wm.boxH * modelData.yf) - wm.inset
        // Stepped by wm.t (a coarse Timer) rather than a per-frame
        // animation: a per-frame NumberAnimation forces a scene repaint at
        // the display's full refresh (120 Hz on ProMotion), which idled the
        // whole app at ~30% CPU. At these drift speeds a 20 Hz step
        // (<0.5 px per tick) is visually identical and repaints 6x less.
        x: tile.width > 0 ? -Math.round(((wm.t * modelData.k + modelData.ph) % 1) * tileW) : 0
        Text {
          id: tile
          textFormat: Text.PlainText
          text: modelData.pat.repeat(reps)
          font.family: mono
          font.pixelSize: Math.max(2, Math.round(modelData.px * wm.uscale))
          color: modelData.col
          opacity: modelData.op
          font.letterSpacing: -0.5
        }
        Text {
          textFormat: Text.PlainText
          text: modelData.pat.repeat(reps)
          font.family: mono
          font.pixelSize: tile.font.pixelSize
          color: modelData.col
          opacity: modelData.op
          font.letterSpacing: -0.5
        }
      }
    }

    // ASCII lightning: four independent strike slots. Each strike picks a
    // random shape, size and position, then waits a random beat before the
    // next, so bolts land in different places at different times, sometimes
    // spread out, sometimes overlapping, instead of a fixed metronome loop.
    Repeater {
      model: 4
      delegate: Text {
        id: boltTx
        textFormat: Text.PlainText
        required property int index
        readonly property var shapes: ["\\\n \\\n /\n/", "/\n\\\n \\\n  /", "\\\n \\/\n  \\", "\\\n/\n\\\n \\", "\\\n \\", " /\n/\n\\", "/\n \\\n  \\\n  /", "\\\n \\\n  \\/\n  /\n /"]
        function strike() {
          text = shapes[Math.floor(Math.random() * shapes.length)]
          font.pixelSize = Math.max(6, Math.round((7 + Math.random() * 5) * wm.uscale))
          x = Math.round(wm.boxW * (0.05 + Math.random() * 0.84)) - wm.inset
          y = Math.round(wm.boxH * (Math.random() * 0.16)) - wm.inset
          bolt.restart()
        }
        function rearm(first) {
          // First strike after hover lands quickly (slot-staggered);
          // afterwards each slot free-runs on its own random beat.
          pauseT.interval = first ? index * 140 + Math.random() * 500 : 150 + Math.random() * 2100
          pauseT.restart()
        }
        color: "#eafff1"
        font.family: mono
        font.bold: true
        lineHeight: 0.78
        opacity: 0
        // One full strike cycle (flicker -> fade to 0). It re-arms itself
        // rather than binding `running: wm.storm` so that when the mouse
        // leaves mid-strike the bolt finishes fading out instead of
        // freezing at whatever opacity it was caught on.
        SequentialAnimation on opacity {
          id: bolt
          running: false
          NumberAnimation {
            to: 1.0
            duration: 40
          }
          NumberAnimation {
            to: 0.12
            duration: 60
          }
          NumberAnimation {
            to: 0.88
            duration: 50
          }
          NumberAnimation {
            to: 0.0
            duration: 130
          }
          onStopped: if (wm.storm)
            boltTx.rearm(false)
        }
        Timer {
          id: pauseT
          repeat: false
          onTriggered: if (wm.storm)
            boltTx.strike()
        }
        Connections {
          target: wm
          function onStormChanged() {
            if (wm.storm && !bolt.running && !pauseT.running)
              boltTx.rearm(true)
          }
        }
      }
    }

    // Idle lightning: a fixed 20-second storm storyboard that loops
    // identically, seven strikes spread far apart. Big bolts frame the
    // box left and right, smaller ones scatter between, and the tall
    // centre strike lights the whole box with a brief sheet flash.
    // Every strike lives the same ~280ms flicker (near-full pre-flash,
    // dark beat, full flash, dim afterglow, the cadence read from the
    // README banner). Deliberately sparse: the free-running random
    // storm above stays a hover-only reward, and these hide while it
    // runs. `at` is milliseconds into the loop.
    Rectangle {
      // Sheet flash for the big centre strike: the whole clip blinks
      // faintly white during that bolt's full-flash beat.
      anchors.fill: parent
      color: "#eafff1"
      readonly property real ms: wm.idleT * wm.idleLoopSecs * 1000 - 9600
      opacity: wm.storm || ms < 140 || ms >= 280 ? 0 : ms < 210 ? 0.13 : 0.05
    }
    Repeater {
      // Every bolt hangs from the box's top edge (yf 0): with no
      // clouds drawn, the frame itself is the sky, so a bolt starting
      // mid-air would read as coming from nowhere. Short bolts are
      // distant strikes; the tall ones reach down toward the swell.
      model: [
        {
          at: 1400,
          shape: "\\\n \\\n /\n/",
          xf: 0.06,
          yf: 0,
          px: 9
        }   // big, far left
        ,
        {
          at: 4200,
          shape: "\\\n \\",
          xf: 0.56,
          yf: 0,
          px: 5
        }   // small
        ,
        {
          at: 6800,
          shape: " /\n/\n\\",
          xf: 0.30,
          yf: 0,
          px: 5.5
        } // small
        ,
        {
          at: 9600,
          shape: "\\\n \\\n  \\/\n  /\n /",
          xf: 0.45,
          yf: 0,
          px: 10
        }  // big centre + flash
        ,
        {
          at: 13000,
          shape: "\\\n/\n\\\n \\",
          xf: 0.74,
          yf: 0,
          px: 5
        }   // small
        ,
        {
          at: 15800,
          shape: "/\n \\\n  \\\n  /",
          xf: 0.88,
          yf: 0,
          px: 9
        }   // big, far right
        ,
        {
          at: 18200,
          shape: " /\n/\n\\",
          xf: 0.18,
          yf: 0,
          px: 4.5
        }  // small
      ]
      delegate: Text {
        required property var modelData
        readonly property real ms: wm.idleT * wm.idleLoopSecs * 1000 - modelData.at
        textFormat: Text.PlainText
        text: modelData.shape
        x: Math.round((wm.boxW - 2 * wm.inset) * modelData.xf)
        y: Math.round((wm.boxH - 2 * wm.inset) * modelData.yf)
        color: "#eafff1"
        font.family: mono
        font.bold: true
        font.pixelSize: Math.max(4, Math.round(modelData.px * wm.uscale))
        lineHeight: 0.78
        opacity: wm.storm || ms < 0 || ms >= 280 ? 0 : ms < 70 ? 0.85 : ms < 140 ? 0 : ms < 210 ? 1 : 0.45
      }
    }
  }

  // Hover -> storm (lightning). NoButton so it never eats clicks.
  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    acceptedButtons: Qt.NoButton
    onEntered: wm.storm = true
    onExited: wm.storm = false
  }
}

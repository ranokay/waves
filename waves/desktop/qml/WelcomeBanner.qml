import QtQuick
import "primitives" as Primitives

// Wide "Welcome to Waves" banner for the login card: the WaveMark parallax ocean
// at banner scale, with the title scrolling as a marquee (or centered) over it.
// `host` is Main.qml's root object, bound at its single instantiation
// (the welcome picker's card column) and required so a missed binding
// fails at load.
// It reads through it:
//   host.mono  the bundled mono font (the file's own `mono` bool means
//     "render the title in mono", so the family is read through host)
//   host.onScreen / host.signedIn
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: banner
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentContTx: "#86ffaa"   // text on accent container
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color green: "#3ef08a"   // LOSSLESS tier + done state

  property string title: "Welcome to Waves"
  property bool marquee: false
  property bool mono: false
  property color ink: "#eef1f4"
  property int titleSize: 40
  property bool bold: true
  property bool scrim: true
  property real wavePxPerSec: 12          // calm, matches the header logo
  property real waveScale: 0.80           // glyph size vs. the 34px logo reference
  property real titleSpeed: 26            // marquee px/sec
  readonly property int inset: 3
  readonly property string titleFamily: mono ? host.mono : Qt.application.font.family
  readonly property string phrase: title + "    •    "

  implicitWidth: 404
  implicitHeight: 75
  radius: 8
  color: "#04140a"
  border.color: accentDim
  border.width: 1

  Item {
    id: bclip
    anchors.fill: parent
    anchors.margins: banner.inset
    clip: true

    // parallax ASCII ocean (the same patterns as the header WaveMark)
    Repeater {
      model: [
        {
          yf: 0.04,
          px: 8,
          op: 0.50,
          par: 0.42,
          pat: "   '    .     *   :   .   ",
          col: accentContTx
        },
        {
          yf: 0.17,
          px: 8,
          op: 0.44,
          par: 0.55,
          pat: ".~-~..-~-.~..-~-.",
          col: green
        },
        {
          yf: 0.30,
          px: 10,
          op: 0.60,
          par: 0.70,
          pat: "~-._.,~-._.,~-._.,",
          col: green
        },
        {
          yf: 0.43,
          px: 11,
          op: 0.76,
          par: 0.84,
          pat: "_.-~-._.,-~-._.-",
          col: accent
        },
        {
          yf: 0.56,
          px: 14,
          op: 0.94,
          par: 1.00,
          pat: "_.-~^~-._.~^'~._",
          col: accent
        },
        {
          yf: 0.69,
          px: 17,
          op: 1.00,
          par: 1.18,
          pat: "_.-~^'~-._/\\.-~^~_.",
          col: accent
        }
      ]
      delegate: Row {
        required property var modelData
        y: Math.round(banner.height * modelData.yf) - banner.inset
        Text {
          id: wtile
          textFormat: Text.PlainText
          text: modelData.pat.repeat(8)
          font.family: host.mono
          font.pixelSize: Math.round(modelData.px * banner.waveScale)
          color: modelData.col
          opacity: modelData.op
          font.letterSpacing: -1
        }
        Text {
          textFormat: Text.PlainText
          text: modelData.pat.repeat(8)
          font.family: host.mono
          font.pixelSize: Math.round(modelData.px * banner.waveScale)
          color: modelData.col
          opacity: modelData.op
          font.letterSpacing: -1
        }
        NumberAnimation on x {
          // Only run while the banner can actually show (it rides
          // the welcome surface, which is signed-out only). QML
          // animations don't stop on invisibility, so gate them
          // off once signed in.
          running: wtile.width > 0 && !host.signedIn && host.onScreen
          from: 0
          to: -wtile.width
          duration: Math.max(1, Math.round(wtile.width / (banner.wavePxPerSec * modelData.par) * 1000))
          loops: Animation.Infinite
        }
      }
    }

    // legibility scrim: dark central band, transparent top & bottom
    Rectangle {
      anchors.fill: parent
      visible: banner.scrim
      gradient: Gradient {
        GradientStop {
          position: 0.0
          color: "#00060810"
        }
        GradientStop {
          position: 0.32
          color: "#bf060810"
        }
        GradientStop {
          position: 0.68
          color: "#bf060810"
        }
        GradientStop {
          position: 1.0
          color: "#00060810"
        }
      }
    }

    TextMetrics {
      id: phraseM
      font.family: banner.titleFamily
      font.pixelSize: banner.titleSize
      font.bold: banner.bold
      text: banner.phrase
    }

    // marquee: the phrase scrolls continuously (a •-separated ticker)
    Item {
      anchors.fill: parent
      clip: true
      visible: banner.marquee
      Item {
        id: mqMove
        anchors.verticalCenter: parent.verticalCenter
        width: mqMain.implicitWidth
        height: mqMain.implicitHeight
        Text {
          textFormat: Text.PlainText
          x: 0
          y: 1
          text: mqMain.text
          font: mqMain.font
          color: "#0a160d"
          opacity: 0.9
        }   // shadow for legibility
        Text {
          id: mqMain
          textFormat: Text.PlainText
          x: 0
          y: 0
          text: banner.phrase.repeat(8)
          font.family: banner.titleFamily
          font.pixelSize: banner.titleSize
          font.bold: banner.bold
          color: banner.ink
        }
        NumberAnimation on x {
          // Same gating as the wave layers: stop once signed in / hidden.
          running: phraseM.advanceWidth > 0 && !host.signedIn && host.onScreen
          from: 0
          to: -phraseM.advanceWidth
          duration: Math.max(1, Math.round(phraseM.advanceWidth / banner.titleSpeed * 1000))
          loops: Animation.Infinite
        }
      }
    }

    // static: the phrase centered, waves moving behind it
    Item {
      anchors.fill: parent
      visible: !banner.marquee
      Text {
        textFormat: Text.PlainText
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 1
        text: banner.title
        font.family: banner.titleFamily
        font.pixelSize: banner.titleSize
        font.bold: banner.bold
        color: "#0a160d"
        opacity: 0.9
      }   // shadow
      Text {
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: banner.title
        font.family: banner.titleFamily
        font.pixelSize: banner.titleSize
        font.bold: banner.bold
        color: banner.ink
      }
    }

    // marquee edge fades (soften the wrap at both ends)
    Rectangle {
      visible: banner.marquee
      anchors.left: parent.left
      anchors.top: parent.top
      anchors.bottom: parent.bottom
      width: 30
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop {
          position: 0.0
          color: "#04140a"
        }
        GradientStop {
          position: 1.0
          color: "#0004140a"
        }
      }
    }
    Rectangle {
      visible: banner.marquee
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.bottom: parent.bottom
      width: 30
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop {
          position: 0.0
          color: "#0004140a"
        }
        GradientStop {
          position: 1.0
          color: "#04140a"
        }
      }
    }
  }
}

import QtQuick

// CRT-tube nav tab ("Tube C" static-burst). At rest each tab is a dim
// phosphor-green panel with a grey label. On select it powers on like an old
// CRT: a burst of scanline static, then the panel strikes in from a collapsed
// line (x, then y overshoot). Power-off crackles with static and collapses
// back to a line, leaving a brief afterglow bar. Shared by the nav tabs.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Item {
  id: nt
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color accentSoft: "#9dffbe"   // CRT flash / phosphor highlight
  readonly property int btnPadH: 12             // label padding, left/right
  readonly property int btnPadV: 7              // label padding, top/bottom
  readonly property int btnRad: 8              // button corner radius
  readonly property real btnTrack: 0              // label letter-spacing
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)

  property string label: ""
  property bool active: false
  signal clicked
  implicitHeight: navMetric.implicitHeight + btnPadV * 2
  implicitWidth: navMetric.implicitWidth + btnPadH * 2
  // A tab is a button: named by its label, reachable with Tab, and
  // Enter/Space fire the same clicked() the pointer does.
  activeFocusOnTab: nt.visible
  Accessible.role: Accessible.Button
  Accessible.name: nt.label
  Accessible.checkable: true
  Accessible.checked: nt.active
  Accessible.onPressAction: nt.clicked()
  Keys.onReturnPressed: function (event) {
    if (!event.isAutoRepeat) {
      event.accepted = true
      nt.clicked()
    }
  }
  Keys.onEnterPressed: function (event) {
    if (!event.isAutoRepeat) {
      event.accepted = true
      nt.clicked()
    }
  }
  Keys.onSpacePressed: function (event) {
    if (!event.isAutoRepeat) {
      event.accepted = true
      nt.clicked()
    }
  }

  // Colours for the CRT look. accent/accentCont/accentDim/accentSoft are the
  // app's shared tokens (copied locally above); the dim phosphor-panel tones
  // are local to this look.
  readonly property color navDimBg: "#0b140f"
  readonly property color navDimBorder: "#1f3d2a"
  readonly property color navDimHover: "#2c5c3e"
  readonly property color navText: "#8f949e"
  readonly property color navTextHi: "#bcc1c9"
  readonly property color navStatic: "#aeb4ad"

  // hidden metric, reserves width so the label never reflows
  Text {
    id: navMetric
    visible: false
    textFormat: Text.PlainText
    text: nt.label
    font.pixelSize: 13
    font.family: uiFont
    font.bold: true
    font.letterSpacing: btnTrack
  }

  // idle body: dim phosphor panel; grey label that greys → green
  Rectangle {
    id: navDim
    anchors.fill: parent
    radius: btnRad
    color: nt.navDimBg
    border.width: 1
    border.color: navMa.containsMouse ? nt.navDimHover : nt.navDimBorder
    Behavior on border.color {
      ColorAnimation {
        duration: 180
      }
    }
    Text {
      anchors.centerIn: parent
      text: nt.label
      textFormat: Text.PlainText
      font.pixelSize: 13
      font.family: uiFont
      font.bold: true
      font.letterSpacing: btnTrack
      color: navMa.containsMouse ? nt.navTextHi : nt.navText
      opacity: nt.active ? 0 : 1
      Behavior on opacity {
        NumberAnimation {
          duration: 220
          easing.type: Easing.OutQuad
        }
      }
      Behavior on color {
        ColorAnimation {
          duration: 180
        }
      }
    }
  }

  // lit body, collapses in / out like a CRT tube
  Rectangle {
    id: navLit
    anchors.fill: parent
    radius: btnRad
    color: accentCont
    border.width: 1
    border.color: accentDim
    opacity: 0
    transform: Scale {
      id: navSc
      origin.x: nt.width / 2
      origin.y: nt.height / 2
      xScale: 0.02
      yScale: 0.02
    }
    Text {
      anchors.centerIn: parent
      text: nt.label
      textFormat: Text.PlainText
      color: accent
      font.pixelSize: 13
      font.family: uiFont
      font.bold: true
      font.letterSpacing: btnTrack
    }
  }

  // static: a stack of uneven scan segments that flicker together
  Item {
    id: navStat
    anchors.fill: parent
    opacity: 0
    clip: true
    Column {
      anchors.centerIn: parent
      spacing: 3
      Repeater {
        model: 5
        delegate: Rectangle {
          required property int index
          width: nt.width * (0.35 + 0.12 * ((index * 3 + 1) % 5))
          height: 2
          radius: 1
          anchors.horizontalCenter: parent.horizontalCenter
          color: index % 2 === 0 ? accent : nt.navStatic
          opacity: 0.5 + 0.1 * (index % 3)
        }
      }
    }
  }

  Rectangle {
    id: navFlash
    anchors.centerIn: parent
    width: parent.width
    height: 3
    radius: 2
    color: accentSoft
    opacity: 0
  }
  Rectangle {
    id: navAfter
    anchors.centerIn: parent
    width: 7
    height: 3
    radius: 2
    color: accent
    opacity: 0
  }

  MouseArea {
    id: navMa
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: nt.clicked()
  }
  Rectangle {
    anchors.fill: parent
    radius: btnRad
    color: "transparent"
    border.width: 2
    border.color: accent
    visible: nt.activeFocus
  }

  states: State {
    name: "on"
    when: nt.active
    PropertyChanges {
      navLit.opacity: 1
    }
    PropertyChanges {
      navSc.xScale: 1
      navSc.yScale: 1
    }
  }
  // Choreography rule: the tube must MOVE on the click frame. The static
  // burst and flash are overlays that ride on top of the strike/collapse,
  // never gates in front of it; a sequential chain here once meant 130 ms
  // of dead flicker before anything lit, which read as input lag.
  transitions: [
    Transition {
      to: "on"
      ParallelAnimation {
        SequentialAnimation {   // static burst rides the strike
          NumberAnimation {
            target: navStat
            property: "opacity"
            to: 0.7
            duration: 24
          }
          NumberAnimation {
            target: navStat
            property: "opacity"
            to: 0.2
            duration: 24
          }
          NumberAnimation {
            target: navStat
            property: "opacity"
            to: 0.6
            duration: 21
          }
          NumberAnimation {
            target: navStat
            property: "opacity"
            to: 0.0
            duration: 63
          }
        }
        SequentialAnimation {
          PropertyAction {
            target: navAfter
            property: "opacity"
            value: 0
          }
          PropertyAction {
            target: navLit
            property: "opacity"
            value: 1
          }
          NumberAnimation {
            target: navSc
            property: "xScale"
            from: 0.02
            to: 1
            duration: 83
            easing.type: Easing.OutCubic
          }
          ParallelAnimation {
            NumberAnimation {
              target: navSc
              property: "yScale"
              from: 0.02
              to: 1
              duration: 111
              easing.type: Easing.OutBack
            }
            SequentialAnimation {
              NumberAnimation {
                target: navFlash
                property: "opacity"
                to: 0.65
                duration: 38
              }
              NumberAnimation {
                target: navFlash
                property: "opacity"
                to: 0.0
                duration: 128
              }
            }
          }
        }
      }
    },
    Transition {
      from: "on"
      ParallelAnimation {
        SequentialAnimation {   // static crackle rides the collapse
          NumberAnimation {
            target: navStat
            property: "opacity"
            to: 0.75
            duration: 24
          }
          NumberAnimation {
            target: navStat
            property: "opacity"
            to: 0.25
            duration: 28
          }
          NumberAnimation {
            target: navStat
            property: "opacity"
            to: 0.6
            duration: 24
          }
          NumberAnimation {
            target: navStat
            property: "opacity"
            to: 0.0
            duration: 77
          }
        }
        SequentialAnimation {
          NumberAnimation {
            target: navSc
            property: "yScale"
            to: 0.05
            duration: 90
            easing.type: Easing.InCubic
          }
          PropertyAction {
            target: navLit
            property: "opacity"
            value: 0
          }
          ParallelAnimation {
            NumberAnimation {
              target: navSc
              property: "xScale"
              to: 0.02
              duration: 83
              easing.type: Easing.InCubic
            }
            NumberAnimation {
              target: navFlash
              property: "opacity"
              to: 0.85
              duration: 83
            }
          }
          ParallelAnimation {
            NumberAnimation {
              target: navFlash
              property: "opacity"
              to: 0.0
              duration: 63
            }
            SequentialAnimation {
              PropertyAction {
                target: navAfter
                property: "opacity"
                value: 0.55
              }
              NumberAnimation {
                target: navAfter
                property: "opacity"
                to: 0.0
                duration: 306
                easing.type: Easing.InQuad
              }
            }
          }
        }
      }
    }
  ]
}

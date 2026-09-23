import QtQuick
import QtQuick.Layouts

// Tap-card option: title + description + optional mono chip, arrow right.
// Used where a gate offers a choice; tapping the card takes the action,
// so there is no separate confirm button. highlight marks the recommended
// (accent-tinted) option.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: gcard
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color surface0: "#121418"   // topbar / statusbar / expand panel
  readonly property color surface3: "#1d2128"   // art bg / unlit meter / inset
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"

  property string title: ""
  property string desc: ""
  property string chip: ""
  property bool highlight: false
  signal clicked
  Layout.fillWidth: true
  implicitHeight: gcRow.implicitHeight + 24
  radius: 10
  color: highlight ? (gcMa.containsMouse ? Qt.lighter(accentCont, 1.35) : accentCont) : (gcMa.containsMouse ? surface3 : surface0)
  border.width: 1
  border.color: highlight ? accentDim : (gcMa.containsMouse ? outline : border1)
  RowLayout {
    id: gcRow
    anchors.verticalCenter: parent.verticalCenter
    x: 14
    width: parent.width - 28
    spacing: 10
    ColumnLayout {
      Layout.fillWidth: true
      spacing: 2
      RowLayout {
        Layout.fillWidth: true
        spacing: 8
        Text {
          textFormat: Text.PlainText
          text: gcard.title
          color: gcard.highlight ? accent : textHi
          font.pixelSize: 13
          font.bold: true
        }
        Text {
          textFormat: Text.PlainText
          visible: gcard.chip !== ""
          text: gcard.chip
          color: accent
          font.family: mono
          font.pixelSize: 9
          font.bold: true
          font.letterSpacing: 0.8
        }
        Item {
          Layout.fillWidth: true
        }
      }
      Text {
        textFormat: Text.PlainText
        visible: gcard.desc !== ""
        text: gcard.desc
        color: textDim
        font.pixelSize: 11
        wrapMode: Text.WordWrap
        lineHeight: 1.2
        Layout.fillWidth: true
      }
    }
    Ico {
      name: "arrow-right"
      color: gcard.highlight ? accent : textDim
      size: 15
      Layout.alignment: Qt.AlignVCenter
    }
  }
  TapAction {
    id: gcMa
    anchors.fill: parent
    // The host's own state, not the tap area's default: a disabled card is
    // no tab stop, no press target and no hand cursor.
    enabled: gcard.enabled
    // The chip (RECOMMENDED, the detected version) is what tells two cards
    // in one gate apart, so it rides the spoken name too.
    accessibleLabel: gcard.title + (gcard.chip !== "" ? ", " + gcard.chip : "") + (gcard.desc !== "" ? ", " + gcard.desc : "")
    focusRadius: gcard.radius
    onTriggered: gcard.clicked()
  }
}

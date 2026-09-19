import QtQuick
import QtQuick.Layouts

// Section header above every capped or collapsible list: the label
// (optionally a link that opens the whole set, marked with the same "›"
// the art-style cloud headlines use), an optional collapse chevron whose
// state the caller owns, a rule out to an optional count badge, and an
// optional trailing control (the artist VIDEOS download-all button) that
// sits above the header's own collapse target.
// Split out of Main.qml (#315 slice 6). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Item {
  id: secHead
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color divider: "#22262d"
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  property string label: ""
  property int count: -1
  // Collapsible mode (artist-page sections): shows a chevron, makes the
  // whole header a click target, and the caller owns the state (so it
  // can persist it via prefs).
  property bool collapsible: false
  property bool collapsed: false
  signal toggled
  // Openable mode: the headline itself is a link to the whole set, marked
  // with the same "›" the art-style cloud headlines use. Only the label
  // is the target, never the rule that runs to the count badge.
  property bool openable: false
  signal opened
  // Optional trailing control (the VIDEOS download-all button), sits
  // between the rule and the count badge. The row takes z 1 so the
  // control's own MouseArea receives clicks above the whole-header
  // collapse target; nothing else in the row accepts mouse events (the
  // openable label's MouseArea is disabled outside openable mode), so
  // header and label clicks fall through to secMa exactly as before.
  property Component trailing: null
  anchors.left: parent ? parent.left : undefined
  anchors.right: parent ? parent.right : undefined
  implicitHeight: 36
  RowLayout {
    z: 1   // lets the trailing control sit above secMa
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 7
    spacing: 12
    ExpandChevron {
      visible: secHead.collapsible
      open: !secHead.collapsed
      hovered: secMa.containsMouse
      tile: 20
      glyph: 14
      showTile: false
      stroke: secMa.containsMouse ? accent : textLo
      Layout.alignment: Qt.AlignVCenter
    }
    Text {
      id: secLabel
      textFormat: Text.PlainText
      text: secHead.openable ? secHead.label + "  ›" : secHead.label
      color: (secHead.collapsible && secMa.containsMouse) || (secHead.openable && secOpenMa.containsMouse) ? textHi : textLo
      font.pixelSize: 12
      font.bold: true
      font.letterSpacing: 1.9
      MouseArea {
        id: secOpenMa
        anchors.fill: parent
        enabled: secHead.openable
        hoverEnabled: secHead.openable
        cursorShape: secHead.openable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: secHead.opened()
      }
    }
    Rectangle {
      Layout.fillWidth: true
      height: 1
      color: divider
    }
    Loader {
      active: secHead.trailing !== null
      visible: active
      sourceComponent: secHead.trailing
      Layout.alignment: Qt.AlignVCenter
    }
    Rectangle {
      visible: count >= 0
      radius: 4
      color: "transparent"
      border.color: border1
      implicitHeight: 18
      implicitWidth: cntT.implicitWidth + 16
      Text {
        id: cntT
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: count
        color: textDim
        font.family: mono
        font.pixelSize: 11
      }
    }
  }
  MouseArea {
    id: secMa
    anchors.fill: parent
    enabled: secHead.collapsible
    hoverEnabled: secHead.collapsible
    cursorShape: secHead.collapsible ? Qt.PointingHandCursor : Qt.ArrowCursor
    onClicked: secHead.toggled()
  }
}

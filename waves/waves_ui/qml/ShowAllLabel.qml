import QtQuick

// SHOW ALL / SHOW LESS label used beneath every capped list (top tracks,
// search sections, artist strip). Mint green at rest (accentContTx, the
// soft container green) so it reads as clickable without shouting; hover
// brightens to full accent. Static by user choice: the sheen sweep from
// scratchpad/showall_design_lab2.qml was tried and pulled as distracting.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.scrollCollapsedToSection(item)  scroll the page back to the section
// Split out of Main.qml (#315 slice 6). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Item {
  id: sa
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentContTx: "#86ffaa"   // text on accent container

  property bool expanded: false
  property int count: 0
  // The section's header item: SHOW LESS scrolls the view back to it
  // (host.scrollCollapsedToSection) instead of leaving the page clamped
  // to the bottom after the rows vanish.
  property Item sectionTop: null
  signal toggled
  implicitWidth: saText.implicitWidth
  implicitHeight: saText.implicitHeight
  width: implicitWidth
  height: implicitHeight
  Text {
    id: saText
    textFormat: Text.PlainText
    text: sa.expanded ? "SHOW LESS" : "SHOW ALL " + sa.count
    color: saMa.containsMouse ? accent : accentContTx
    font.pixelSize: 12
    font.bold: true
    font.letterSpacing: 1.4
    Behavior on color {
      ColorAnimation {
        duration: 90
      }
    }
  }
  MouseArea {
    id: saMa
    anchors.fill: parent
    anchors.margins: -4
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: {
      // Capture before toggled() flips the bound expanded state.
      var collapsing = sa.expanded
      sa.toggled()
      if (collapsing && sa.sectionTop)
        host.scrollCollapsedToSection(sa.sectionTop)
    }
  }
}

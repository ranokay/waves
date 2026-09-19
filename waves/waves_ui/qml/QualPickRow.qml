import QtQuick

// One row of a QualPick's menu: the tier as a pill-shaped line (dot, word,
// spec) resting in white like the Settings dropdown, lit in the tier's own
// colours under the pointer and on the tier a download would ask for; a
// DEFAULT mark on the setting's tier, NOT OFFERED (dimmed, inert) on a tier
// the catalog cannot land for this item.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.hoverMotion / host.libraryWord / host.qualBorder / host.qualDot /
//   host.qualFg / host.qualSpec / host.qualSpecFg / host.qualTint /
//   host.targetTier
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Rectangle {
  id: qpr
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color libAccent: "#e5a00d"
  readonly property color libContTx: "#f2c766"
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  property var pick: null
  property string t: ""
  readonly property bool isDefault: t === host.targetTier
  readonly property bool isCurrent: pick && t === pick.effective
  readonly property bool ok: pick ? pick.offered(t) : true
  // The copy on disk is this tier: say so, in the library badge's own
  // amber, so "you already have it" never reads as one of the tier
  // colours the rest of the row is spoken in.
  readonly property bool inLibrary: pick !== null && pick.ownedTier !== "" && t === pick.ownedTier
  readonly property bool hovering: rowMa.containsMouse && ok
  readonly property bool lit: hovering || isCurrent
  width: pick ? pick.menuW - 8 : 188
  implicitHeight: 22
  radius: 4
  color: lit ? host.qualTint(t) : "transparent"
  border.width: 1
  border.color: lit ? host.qualBorder(t) : "transparent"
  opacity: ok ? 1 : 0.6
  scale: hovering ? 1.04 : 1
  transformOrigin: Item.Center
  Behavior on color {
    ColorAnimation {
      duration: host.hoverMotion ? 110 : 0
    }
  }
  Behavior on border.color {
    ColorAnimation {
      duration: host.hoverMotion ? 110 : 0
    }
  }
  Behavior on scale {
    NumberAnimation {
      duration: host.hoverMotion ? 140 : 0
      easing.type: Easing.OutBack
    }
  }
  Row {
    anchors.left: parent.left
    anchors.leftMargin: 8
    anchors.verticalCenter: parent.verticalCenter
    spacing: 6
    Rectangle {
      anchors.verticalCenter: parent.verticalCenter
      width: 6
      height: 6
      radius: 3
      color: host.qualDot(qpr.t)
    }
    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      text: qpr.t
      color: qpr.lit ? host.qualFg(qpr.t) : textHi
      font.family: mono
      font.pixelSize: 10
      font.bold: true
      Behavior on color {
        ColorAnimation {
          duration: host.hoverMotion ? 110 : 0
        }
      }
    }
    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      text: host.qualSpec(qpr.t)
      color: qpr.lit ? host.qualSpecFg(qpr.t) : textHi
      font.family: mono
      font.pixelSize: 10
      Behavior on color {
        ColorAnimation {
          duration: host.hoverMotion ? 110 : 0
        }
      }
    }
  }
  Row {
    anchors.right: parent.right
    anchors.rightMargin: 8
    anchors.verticalCenter: parent.verticalCenter
    spacing: 6
    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      visible: qpr.isDefault || !qpr.ok
      text: !qpr.ok ? "NOT OFFERED" : "DEFAULT"
      color: qpr.lit ? textHi : textLo
      font.family: mono
      font.pixelSize: 9
    }
    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      visible: qpr.inLibrary
      text: host.libraryWord
      color: qpr.lit ? libContTx : libAccent
      font.family: mono
      font.pixelSize: 9
      font.bold: true
      Behavior on color {
        ColorAnimation {
          duration: host.hoverMotion ? 110 : 0
        }
      }
    }
    Ico {
      visible: qpr.isCurrent
      anchors.verticalCenter: parent.verticalCenter
      name: "check"
      color: host.qualFg(qpr.t)
      size: 10
      bold: 8
    }
  }
  MouseArea {
    id: rowMa
    anchors.fill: parent
    hoverEnabled: true
    enabled: qpr.ok
    cursorShape: Qt.PointingHandCursor
    onClicked: if (qpr.pick)
      qpr.pick.choose(qpr.t)
  }
}

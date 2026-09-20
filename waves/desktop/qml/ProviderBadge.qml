import QtQuick

// Provider badge: the official logo chip overlaid top-right
// of drill header artwork, so a page names its provider at a glance.
// The badge is a fixed chip and every mark fits one box; only the
// descriptor the bridge answers chooses which mark.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: pb
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)

  // The provider's descriptor, from the bridge: the badge
  // renders the mark it carries, so a third registered provider badges
  // like the first two and no id prefix or asset path is parsed here.
  // The mark fits one shared box; the descriptor's own header sizes stay
  // for the section heads.
  property var descriptor: null
  readonly property string mark: pb.descriptor ? String(pb.descriptor.logo || "") : ""
  visible: pb.mark !== ""
  width: 34
  height: 24
  radius: 7
  color: "#cc101318"
  border.color: outline
  Image {
    anchors.centerIn: parent
    source: pb.descriptor ? String(pb.descriptor.logo || "") : ""
    width: 18
    height: 14
    fillMode: Image.PreserveAspectFit
    smooth: true
    cache: true
  }
}

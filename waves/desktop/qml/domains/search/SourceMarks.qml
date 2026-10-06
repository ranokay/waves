import QtQuick
import QtQuick.Controls.Basic
import "../providers"

// Compact source identity for one search row: a mark per provider that
// returned this item -- one for an unmerged (uncertain) row, several once
// high-confidence equivalents fold together. Each mark names its provider
// for a screen reader and a hover tooltip; an unknown namespace, whose
// provider is not registered, shows no mark rather than a wrong one.
// The row components place it; passing an empty list hides it, which is what
// a single-source install does (there is nothing to disambiguate).
Row {
  id: marks
  property var sources: []
  spacing: 5
  visible: (marks.sources || []).length > 0

  Repeater {
    model: marks.sources || []
    delegate: Item {
      id: mark
      required property var modelData
      objectName: "searchSourceMark"
      readonly property var descriptor: waves.providerDescriptor(String(mark.modelData.provider || ""))
      visible: mark.descriptor !== null && String(mark.descriptor.logo || "") !== ""
      width: 17
      height: 14
      // A reader hears whose result this is, in registry words: the
      // descriptor owns the name, no id prefix is parsed here.
      Accessible.role: Accessible.StaticText
      Accessible.name: mark.descriptor ? "Available on " + String(mark.descriptor.name || "") : ""
      ProviderLogo {
        anchors.fill: parent
        logo: mark.descriptor ? String(mark.descriptor.logo || "") : ""
        fillMode: Image.PreserveAspectFit
        smooth: true
        cache: true
      }
      MouseArea {
        id: markHover
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
      }
      ToolTip.text: mark.descriptor ? String(mark.descriptor.name || "") : ""
      ToolTip.visible: markHover.containsMouse && ToolTip.text !== ""
    }
  }
}

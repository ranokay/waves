import QtQuick

// Popularity (0-100) shown as a thin meter + number
// Popularity as a 2-row LED matrix (pop lab option 5): one fixed-width
// block in the download-bar language, no trailing number, so stacked
// rows align instead of staggering.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.segColor
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Row {
  id: pm
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color red: "#ff5a52"   // failed / peak / heart

  property int value: 0
  property bool showNum: true   // kept for call-site compat; the matrix has no number
  visible: value >= 0
  spacing: 5
  Ico {
    name: "heart"
    color: red
    size: 12
    anchors.verticalCenter: parent.verticalCenter
  }
  Column {
    spacing: 1.5
    anchors.verticalCenter: parent.verticalCenter
    Repeater {
      model: 2
      delegate: Row {
        required property int index
        readonly property int rowTop: index
        spacing: 1.5
        Repeater {
          model: 10
          delegate: Rectangle {
            required property int index
            // Column-major bottom-up fill, same as the download matrices.
            readonly property int fillIndex: index * 2 + (1 - rowTop)
            readonly property bool lit: fillIndex < Math.round(Math.max(0, Math.min(100, pm.value)) / 100 * 20)
            width: 3
            height: 3
            radius: 0   // sharp LED cells, not rounded
            color: host.segColor(index)
            opacity: lit ? 1.0 : 0.16
          }
        }
      }
    }
  }
}

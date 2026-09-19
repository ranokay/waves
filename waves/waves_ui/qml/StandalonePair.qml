import QtQuick

// First-class standalone lyrics/art actions (spec section 7.3):
// LYRICS / COVER beside DOWNLOAD on album and artist pages, plus the
// per-track pair. Both providers; found and saved music alike (the
// provider resolves rows, not files). Always visible, even per track:
// appearing only on hover would reflow the row.
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Row {
  id: sp
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color textLo: "#a8acb4"

  property string mediaId: ""
  property bool compact: false
  spacing: compact ? 10 : 12
  Text {
    text: "LYRICS"
    color: textLo
    font.pixelSize: compact ? 11 : 12
    font.bold: true
    font.letterSpacing: 0.8
    anchors.verticalCenter: parent.verticalCenter
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: waves.downloadLyricsOnly(sp.mediaId)
    }
  }
  Text {
    text: "COVER"
    color: textLo
    font.pixelSize: compact ? 11 : 12
    font.bold: true
    font.letterSpacing: 0.8
    anchors.verticalCenter: parent.verticalCenter
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: waves.downloadArtOnly(sp.mediaId)
    }
  }
}

import QtQuick

// The quality badge: a tier word, its spec and a coloured dot in the tier's
// own colours (ATMOS wears an outline, not a rung), and the MIXED variant for
// an album that spans tiers.
// 'host' is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load; the tier palette maps come
// through it (host.qualBg / host.qualFg / host.qualBorder / host.qualDot /
// host.qualSpec / host.qualSpecFg).
// Split out of Main.qml (#315 slice 4). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Row {
  id: qt
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color surface2: "#191c22"   // hover / nested
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  property string q: ""
  // Set (via qualMixList) when the album mixes tiers, replaces the
  // single-tier pill with MIXED + per-tier counts (/ sep).
  property var mix: []
  // Real per-item spec when we know it (a video's actual resolution);
  // empty falls back to the tier's standard spec.
  property string spec: ""
  // Narrow surfaces (the queue drawer) show the tier word alone: the
  // spec is what makes the pill wide enough to crush a title.
  property bool compact: false
  readonly property string specText: compact ? "" : (spec !== "" ? spec : host.qualSpec(qt.q))
  readonly property bool mixed: mix.length > 1
  // The pill's colours, as plain properties so a surface that ANIMATES
  // them (QualPick, the badge you can choose a tier on) binds its own
  // eased values here, while every other pill (the queue drawer's
  // hundreds of compact rows included) keeps these static defaults and
  // pays for no Behavior objects.
  property color bg: host.qualBg(qt.q)
  property color edge: host.qualBorder(qt.q)
  property color ink: host.qualFg(qt.q)
  property color specInk: host.qualSpecFg(qt.q)
  property color dotInk: host.qualDot(qt.q)
  // Extra width the pill grows by to admit a caret at its right end; the
  // content shifts left by it so the dot, word and spec keep their air.
  property real extraW: 0
  // Ground and border dropped, leaving the dot, word and spec alone: a
  // copy of a pill laid over the real one to be faded (QualPick's
  // outgoing tier) must not put a second ground and border on the badge.
  property bool chromeless: false
  // Fades the content WITHOUT the pill under it, so a tier change can
  // swap the letters inside a ground that never blinks.
  property real contentOpacity: 1
  // The width the pill wants from its own content. A surface that EASES
  // that width through a change (QualPick again) reads this, eases it,
  // and hands the result back as pillW; -1, which is every other pill in
  // the app, means "size yourself" and costs nothing.
  readonly property real naturalW: mixed ? mixRow.implicitWidth + 16 : tagRow.implicitWidth + 16 + qt.extraW
  property real pillW: -1
  visible: q !== "" || mixed
  Rectangle {
    visible: !qt.mixed
    // The ground is the tier's, not the pill's: ATMOS is an outline
    // (see qualBg), every ladder tier sits on surface2.
    radius: 4
    color: qt.chromeless ? "transparent" : qt.bg
    border.color: qt.chromeless ? "transparent" : qt.edge
    border.width: 1
    implicitHeight: 22
    implicitWidth: qt.pillW >= 0 ? qt.pillW : tagRow.implicitWidth + 16 + qt.extraW
    Row {
      id: tagRow
      anchors.centerIn: parent
      spacing: 6
      anchors.horizontalCenterOffset: -qt.extraW / 2
      opacity: qt.contentOpacity
      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: 6
        height: 6
        radius: 3
        color: qt.dotInk
      }
      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: qt.q
        color: qt.ink
        font.family: mono
        font.pixelSize: 9
        font.bold: true
      }
      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        visible: qt.specText !== ""
        text: qt.specText
        color: qt.specInk
        font.family: mono
        font.pixelSize: 9
      }
    }
  }
  // MIXED, one dot per tier, then per-tier track counts as the spec
  Rectangle {
    visible: qt.mixed
    radius: 4
    color: qt.chromeless ? "transparent" : surface2
    border.color: qt.chromeless ? "transparent" : outline
    border.width: 1
    implicitHeight: 22
    implicitWidth: qt.pillW >= 0 ? qt.pillW : mixRow.implicitWidth + 16
    Row {
      id: mixRow
      anchors.centerIn: parent
      spacing: 6
      opacity: qt.contentOpacity
      Row {
        spacing: 2
        anchors.verticalCenter: parent.verticalCenter
        Repeater {
          model: qt.mix
          delegate: Rectangle {
            required property var modelData
            width: 6
            height: 6
            radius: 3
            color: host.qualDot(modelData.q)
          }
        }
      }
      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: "MIXED"
        color: textHi
        font.family: mono
        font.pixelSize: 9
        font.bold: true
      }
      Repeater {
        // The per-tier counts are the widest thing a pill can
        // carry; on a narrow surface the dots say "not uniform"
        // and the expanded ledger says exactly how.
        model: qt.compact ? [] : qt.mix
        delegate: Row {
          required property var modelData
          required property int index
          spacing: 6
          anchors.verticalCenter: parent.verticalCenter
          Text {
            textFormat: Text.PlainText
            visible: index > 0
            anchors.verticalCenter: parent.verticalCenter
            text: "/"
            color: textDim
            font.family: mono
            font.pixelSize: 9
          }
          Text {
            textFormat: Text.PlainText
            anchors.verticalCenter: parent.verticalCenter
            text: modelData.n + "× " + modelData.q
            color: host.qualSpecFg(modelData.q)
            font.family: mono
            font.pixelSize: 9
          }
        }
      }
    }
  }
}

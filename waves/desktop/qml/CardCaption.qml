import QtQuick

// The card caption line under an art card: title, lead artists and meta.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.cardLeadArtists / host.cardSubLead / host.cardSubMeta /
//   host.cardSubtitle / host.isNewRelease
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Item {
  id: cap
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"

  property var card: ({})
  property int px: 11
  property bool center: false
  property color metaColor: textHi
  // The card says you have it (see NewTag.settled).
  property bool settled: false
  readonly property string lead: host.cardSubLead(card)
  readonly property string meta: host.cardSubMeta(card)
  readonly property string fallback: lead === "" && meta === "" ? host.cardSubtitle(card) : ""
  // Albums test the date their caption shows; a track card shows none,
  // so the mark is its only recency cue.
  readonly property bool fresh: card.kind === "album" ? host.isNewRelease(card.listed || card.date) : card.kind === "track" ? host.isNewRelease(card.date) : false
  implicitHeight: capRow.implicitHeight
  FontMetrics {
    id: capFm
    font.pixelSize: cap.px
  }
  Row {
    id: capRow
    spacing: 4
    anchors.left: cap.center ? undefined : parent.left
    anchors.horizontalCenter: cap.center ? parent.horizontalCenter : undefined
    ArtistLinks {
      host: cap.host
      visible: cap.lead !== ""
      artists: cap.lead !== "" ? host.cardLeadArtists(cap.card) : []
      px: cap.px
      width: Math.min(implicitWidth, cap.width - (cap.meta !== "" ? capMeta.implicitWidth + capDot.implicitWidth + 8 : 0) - (cap.fresh ? capNew.implicitWidth + 4 : 0))
    }
    Text {
      id: capDot
      textFormat: Text.PlainText
      visible: cap.lead !== "" && cap.meta !== ""
      text: "\u00b7"
      color: textDim
      font.pixelSize: cap.px
    }
    Text {
      id: capMeta
      textFormat: Text.PlainText
      visible: cap.meta !== ""
      text: cap.meta
      color: cap.metaColor
      font.pixelSize: cap.px
    }
    // Never taller than the caption's own text line: at 11px that line
    // is 13px, and a 14px mark grew it, nudging everything under the
    // card's caption down by a pixel on the marked cards only.
    NewTag {
      id: capNew
      host: cap.host
      compact: true
      visible: cap.fresh
      settled: cap.settled
      height: Math.min(implicitHeight, Math.floor(capFm.height))
      anchors.verticalCenter: parent.verticalCenter
    }
    Text {
      textFormat: Text.PlainText
      visible: cap.fallback !== ""
      text: cap.fallback
      color: textDim
      font.pixelSize: cap.px
      elide: Text.ElideRight
      width: Math.min(implicitWidth, cap.width)
    }
  }
}

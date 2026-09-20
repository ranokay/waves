import QtQuick

// Console-style Browse card: a framed 156x236 card with the artwork,
// title, caption and download control. The artwork or the title opens the
// card's page, the caption handles its own artist link, and an album card
// carries the library verdict the payload baked (dated with the window's
// stamp).
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.browseCardDownload / host.browseCardOpenable / host.dlPct / host.dlSt /
//   host.fmtMs / host.hoverPrefetch / host.hoverPrefetchCancel /
//   host.ledPulse / host.libStamp / host.marchTick / host.openBrowseCard /
//   host.openLibraryClaim / host.previewPosition / host.pvSt /
//   host.queueEdgeHeld / host.shimmerPhase / host.stopPreview /
//   host.togglePreview
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: bc
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property real btnTrack: 0              // label letter-spacing
  readonly property color cyan: "#56c8d8"   // HIGH tier + queued
  readonly property color gold: "#ffb01f"   // HI-RES / VIDEO tier + meter mid band
  readonly property color green: "#3ef08a"   // LOSSLESS tier + done state
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)

  property var card: ({})
  readonly property string kind: card.kind || ""
  width: 156
  height: 236
  radius: 12
  color: surface
  border.color: border1
  // Only the artwork and the title open the card's page, the caption
  // handles its own artist link, and dead space stays inert. Whether they
  // offer it is Main.qml's browseCardOpenable verdict, the same one the
  // click path reads, so the cursor and the click can never disagree.
  readonly property bool openable: host.browseCardOpenable(bc.card)
  // Resting anywhere on the card has its page ready before the click
  // (see hoverPrefetch). A handler of its own, not the Art's fxHover:
  // that one is off when the user turns the cover tilt off.
  HoverHandler {
    onHoveredChanged: hovered ? host.hoverPrefetch(bc.card) : host.hoverPrefetchCancel(bc.card)
  }
  // Everything the art view previews, previewable here too (videos have
  // no audio-preview path).
  readonly property bool previewable: bc.kind !== "video" && !!bc.card.id
  readonly property string pvSt: previewable ? host.pvSt(bc.kind, bc.card.id || "") : ""
  readonly property string dlSt: host.dlSt(bc.card.id || "")
  readonly property real dlPct: host.dlPct(bc.card.id || "")
  // The library verdict this card carries lives in LibraryVerdict, the
  // one owner both card styles share; the aliases below keep this card's
  // public surface (what the control line and the scenarios read).
  LibraryVerdict {
    id: bcVerdict
    host: bc.host
    card: bc.card
  }
  readonly property var libPresence: bcVerdict.presence
  readonly property bool libPresent: bcVerdict.present
  readonly property bool libFull: bcVerdict.full
  readonly property bool libSure: bcVerdict.sure
  readonly property bool libAtmos: bcVerdict.atmos
  readonly property string libState: bcVerdict.state
  readonly property bool libClaim: bcVerdict.claim
  readonly property string libWord: bcVerdict.word
  // The pill's tier colours, so the two things this card can say never
  // disagree about what a colour means: green proven, gold guess, cyan
  // partial, accent for a plain download.
  readonly property color libInk: bc.libState === "proven" ? green : bc.libState === "maybe" ? gold : bc.libState === "partial" ? cyan : accent
  Column {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: 8
    spacing: 5
    Art {
      host: bc.host
      width: parent.width
      height: parent.width
      hoverFx: true
      // previewable mirrors the strip's own gate, so a video card
      // (no audio preview path) can never claim the raise.
      fxKind: bc.previewable ? bc.kind : ""
      fxId: bc.previewable ? ("" + (bc.card.id || "")) : ""
      url: bc.card.art || ""
      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: bc.openable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: host.openBrowseCard(bc.card)
      }
    }
    Text {
      id: bcTitle
      textFormat: Text.PlainText
      text: bc.card.title || ""
      color: textHi
      font.pixelSize: 12
      font.bold: true
      // Height hugs the actual line count, a one-line title no
      // longer leaves a blank second line above the caption.
      // The ATMOS TOO micro-badge takes the second line's room, so
      // a card showing it holds its title to one line: the caption
      // column and the bottom-anchored control row otherwise meet
      // on two-line titles.
      width: parent.width
      elide: Text.ElideRight
      maximumLineCount: (bc.libPresent && bc.libAtmos) ? 1 : 2
      wrapMode: Text.Wrap
      font.underline: bcTitleMa.containsMouse && bc.openable
      MouseArea {
        id: bcTitleMa
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: Math.min(parent.implicitWidth, parent.width)
        hoverEnabled: true
        cursorShape: bc.openable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: host.openBrowseCard(bc.card)
      }
    }
    // Full-width caption line: the album's artist link + date (or
    // "N tracks") gets the whole row now that the download control
    // lives on its own line below.
    CardCaption {
      host: bc.host
      card: bc.card
      px: 11
      width: parent.width
      settled: bc.dlSt === "done" || bc.libClaim
    }
    // The Atmos micro-badge (§8.4). In the caption column, so it
    // rides the card's own layout; the column skips hidden children,
    // so cards without Atmos keep their exact shape.
    Text {
      visible: bc.libPresent && bc.libAtmos
      textFormat: Text.PlainText
      text: "ATMOS TOO"
      color: textDim
      font.family: mono
      font.pixelSize: 9
      font.bold: true
      width: parent.width
      elide: Text.ElideRight
    }
  }
  // Control line pinned to the bottom edge so shelf rows align:
  // ▶ PREVIEW on the left, bare-text download on the right.
  Item {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.margins: 8
    height: 16
    // preview: ▶ PREVIEW -> ■ + mono elapsed while active
    Item {
      id: bcPv
      // Named so the fit guard can measure the two halves of this
      // line against each other, not just the box.
      objectName: "bcPreview"
      visible: bc.previewable
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      width: bcPvRow.implicitWidth
      height: 16
      // This line is 140px (a 156px card less its margins) and the
      // download box owns the right edge, reserving its widest
      // state, so the preview control only ever gets what is left.
      // Both are anchored, so nothing pushes back: when the words
      // outgrow the room they simply draw through each other. So the
      // preview gives way, the way the art card's strip gives up its
      // padding: the word stands down and the glyph carries the
      // control alone, which always fits. Measured off the parts
      // rather than the Row, because the Row's implicitWidth is what
      // hiding the word changes (reading it here would be a loop).
      readonly property real gapW: 6
      readonly property real icoW: 10
      readonly property real stopW: bcPvStop.visible ? bcPvRow.spacing + bcPvStop.implicitWidth : 0
      readonly property real availW: parent.width - bcDlBox.width - gapW
      readonly property real naturalW: icoW + bcPvRow.spacing + bcPvWord.implicitWidth + stopW
      readonly property bool tight: naturalW > availW
      Row {
        id: bcPvRow
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4
        Ico {
          // The click pauses (togglePreview), it doesn't stop,
          // so the active glyph is a pause, matching the art view.
          visible: bc.pvSt !== "loading"
          name: bc.pvSt === "playing" ? "pause" : "play"
          color: bc.pvSt === "error" ? red : accent
          size: 10
          anchors.verticalCenter: parent.verticalCenter
        }
        Text {
          id: bcPvWord
          visible: !bcPv.tight
          textFormat: Text.PlainText
          text: bc.pvSt === "" ? "PREVIEW" : bc.pvSt === "loading" ? "[buffering]" : bc.pvSt === "error" ? "RETRY" : host.fmtMs(host.previewPosition)
          color: bc.pvSt === "error" ? red : accent
          font.family: bc.pvSt === "playing" || bc.pvSt === "paused" || bc.pvSt === "loading" ? mono : uiFont
          font.pixelSize: 10
          font.bold: true
          font.letterSpacing: btnTrack
          anchors.verticalCenter: parent.verticalCenter
          // Breathe while buffering (same cadence as the dot
          // matrix's pulsing next-block). The animation drives a
          // side property so opacity snaps back to 1 the moment
          // loading ends, instead of freezing mid-breath.
          property real breathe: 1
          opacity: bc.pvSt === "loading" ? breathe : 1
          SequentialAnimation on breathe {
            running: bc.pvSt === "loading"
            loops: Animation.Infinite
            NumberAnimation {
              from: 1.0
              to: 0.3
              duration: 520
              easing.type: Easing.InOutSine
            }
            NumberAnimation {
              from: 0.3
              to: 1.0
              duration: 520
              easing.type: Easing.InOutSine
            }
          }
        }
        // "· STOP" rides after the elapsed counter while a preview
        // is live; quiet at rest, red on hover, resets to idle.
        Text {
          id: bcPvStop
          textFormat: Text.PlainText
          visible: bc.pvSt === "playing" || bc.pvSt === "paused"
          text: "· STOP"
          color: bcStopMa.containsMouse ? red : textDim
          font.family: uiFont
          font.pixelSize: 9
          font.bold: true
          font.letterSpacing: btnTrack
          anchors.verticalCenter: parent.verticalCenter
          MouseArea {
            id: bcStopMa
            anchors.fill: parent
            anchors.margins: -3
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: host.stopPreview()
          }
        }
      }
      MouseArea {
        anchors.fill: parent
        z: -1
        cursorShape: Qt.PointingHandCursor
        onClicked: host.togglePreview(bc.kind, bc.card.id || "", 0)
      }
    }
    // download: DOWNLOAD -> dot bar + fixed-width % -> ✓ DONE
    Item {
      id: bcDlBox
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      width: Math.max(bcDlIdle.implicitWidth, bcDlWordMetric.implicitWidth, bcDlLibMetric.implicitWidth, bcDlRun.implicitWidth, bcDlQueued.implicitWidth)
      height: 16
      // "preparing" reads as queued here too: see DownloadButton.waiting.
      readonly property bool waiting: bc.dlSt === "queued" || bc.dlSt === "preparing"
      // The word here changes with the job (DONE, RETRY) and with
      // the library verdict (DOWNLOAD, IN LIBRARY, MAYBE, N OF M),
      // and this box is anchored to the right edge, so an
      // unreserved width would walk the control left and right as a
      // scan lands. Reserve the two widest once, the same metric
      // trick the full button's dbMetric rows use. The widest live
      // word cannot do the job by itself: the queued row gives up
      // the media noun to fit the line.
      Text {
        id: bcDlWordMetric
        visible: false
        textFormat: Text.PlainText
        text: "DOWNLOAD"
        font.family: uiFont
        font.pixelSize: 10
        font.bold: true
        font.letterSpacing: btnTrack
      }
      Text {
        id: bcDlLibMetric
        visible: false
        textFormat: Text.PlainText
        text: "IN LIBRARY"
        font.family: uiFont
        font.pixelSize: 10
        font.bold: true
        font.letterSpacing: btnTrack
      }
      Text {
        id: bcDlIdle
        // Named so the scenario test can read the WORD the user
        // sees, not just the property that is supposed to pick it.
        objectName: "bcDlWord"
        textFormat: Text.PlainText
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        visible: bc.dlSt !== "running" && !bcDlBox.waiting
        // A download Waves made is the freshest fact this line can
        // state, so DONE outranks any library verdict; only an idle
        // card falls through to what the scan found.
        text: bc.dlSt === "done" ? "DONE" : bc.dlSt === "failed" ? "RETRY" : bc.libWord
        color: bc.dlSt === "done" ? green : bc.dlSt === "failed" ? red : bc.libInk
        font.family: uiFont
        font.pixelSize: 10
        font.bold: true
        font.letterSpacing: btnTrack
      }
      // Queued: the stack glyph and the word, the same language as
      // the full DownloadButton's queued state. The media noun the
      // full button carries is dropped here: the card is already the
      // noun, and "QUEUED ALBUM" plus the glyph came to 101px of a
      // 140px line the preview control also has to live on.
      Row {
        id: bcDlQueued
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        visible: bcDlBox.waiting
        spacing: 5
        QueueStack {
          marchTick: host.marchTick
          barW: 9
          anchors.verticalCenter: parent.verticalCenter
        }
        Text {
          textFormat: Text.PlainText
          text: "QUEUED"
          color: accentDim
          font.family: uiFont
          font.pixelSize: 10
          font.bold: true
          font.letterSpacing: btnTrack
          anchors.verticalCenter: parent.verticalCenter
        }
      }
      Row {
        id: bcDlRun
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        visible: bc.dlSt === "running"
        spacing: 5
        DotMatrix {
          width: 34
          rows: 2
          dot: 4
          gap: 2
          pct: Math.max(0, bc.dlPct)
          finishing: bc.dlPct >= 99.9
          ledPulse: host.ledPulse
          shimmerPhase: host.shimmerPhase
          queueEdgeHeld: host.queueEdgeHeld
          anchors.verticalCenter: parent.verticalCenter
        }
        Text {
          textFormat: Text.PlainText
          text: bc.dlPct >= 0 ? Math.round(bc.dlPct) + "%" : "…"
          // Reserve the widest label ("100%") so the digit count
          // changing never shifts the dot bar.
          width: bcDlMetric.implicitWidth
          horizontalAlignment: Text.AlignRight
          color: accent
          font.family: mono
          font.pixelSize: 9
          font.bold: true
          anchors.verticalCenter: parent.verticalCenter
        }
        Text {
          id: bcDlMetric
          visible: false
          textFormat: Text.PlainText
          text: "100%"
          font.family: mono
          font.pixelSize: 9
          font.bold: true
        }
      }
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          if (bc.dlSt === "running" || bc.dlSt === "done" || bcDlBox.waiting)
            return
          // A full claim opens the claim gate, the same click the
          // full button and the art card's strip give it. A
          // partial copy downloads: with the bulk skip gate on,
          // that fetches the rest.
          if (bc.libClaim) {
            host.openLibraryClaim(bc.card.id || "", "" + (bc.card.title || ""), "" + (bc.libPresence.local_album_id || ""), "album")
            return
          }
          host.browseCardDownload(bc.card)
        }
      }
    }
  }
}

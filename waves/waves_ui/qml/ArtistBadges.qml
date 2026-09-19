import QtQuick

// The artist badge: what this artist holds in your library, fed by the
// artist-level rollup. On artwork it is a full-width STRIP across the
// cover's lower edge rather than a chip in a corner, so it never sits on
// top of a face, and it is drawn on the same gradient the hero card
// already uses to carry a caption over a photograph rather than on a new
// material invented for it.
//
// Two voices only: "IN LIBRARY" in the owned green says what this is, and
// the counts in plain text say how much. No "?" anywhere. The mark belongs
// on an album pill, where it separates a proven identity from a name match;
// a rollup is a count, and a count has nothing to doubt.
//
// Green and not a quality class on purpose: the green is the one the
// download button and the browse card already turn when a release is in the
// library, so one page never says "owned" in two colours. Quality colour is
// the album pill's story, and an artist spanning FLAC and MP3 has no single
// class to tell anyway.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.browseBuilding / host.searchBuilding
// Split out of Main.qml (#315 slice 5). The palette values are local
// copies of Main.qml's static literals — the SettingsPage.qml convention;
// keep them in step if the palette changes.
Item {
  id: arb
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color green: "#3ef08a"   // LOSSLESS tier + done state
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  property string artistName: ""
  property var presence: null
  // Draw as the strip on artwork. The caller sets the width and parents
  // it inside the Art, which clips, so the strip takes the cover's tilt
  // and rounded corners with it. The page form sizes itself to its text.
  property bool bar: false
  // Two lines, the shape the hero card's caption already uses over
  // artwork: a spaced cap line over counts set big enough to survive a
  // photograph, which one rail-height line could never give them.
  //
  // Sized to the cover it is on, not to one cover. A search card's is
  // 184px and a browse card's 200, but the followed-artists grid packs
  // its covers to about 116, where a 12px count line runs 150px wide and
  // an Art that clips simply sliced the ends off both numbers. The type
  // is mono, so the width is arithmetic rather than a guess: 0.6em per
  // character plus the two gaps, floored at 8px so it stops shrinking
  // before it stops being readable.
  readonly property int countChars: arb.albumLine.length + arb.songLine.length + 1
  readonly property real barCountPx: Math.max(8, Math.min(12, (arb.width - 12 - 14) / Math.max(1, arb.countChars) / 0.6))
  readonly property real barLabelPx: Math.max(8, Math.min(10, arb.barCountPx))
  // The words' own band, plus the room the smaller type gives back.
  readonly property real barHeight: Math.max(24, Math.min(34, arb.barCountPx * 2.8))
  implicitWidth: arb.bar ? 0 : abPlate.implicitWidth
  implicitHeight: arb.bar ? arb.barHeight : abPlate.implicitHeight
  width: implicitWidth
  height: implicitHeight
  // The album pill's economy, for the same reason: this now rides every
  // artist card on a search page, and an unconditional resolve here
  // would be a second QML->Python call per card on top of the binding's.
  property bool _resolved: false
  // False until this badge has answered for the name it currently shows.
  // The fade below reads it, so the badge a page is BUILT with (or a
  // recycled row rebound to a new artist) is simply there, and only a
  // badge the running scan turns up while you are looking at it animates.
  property bool _settled: false
  function _resolvePresence() {
    _resolved = true
    presence = artistName !== "" ? waves.artistLibraryPresence(artistName) : null
    _settled = true
    // after the answer, never before: see the Behavior
  }
  onArtistNameChanged: {
    _settled = false
    _resolvePresence()
  }
  Component.onCompleted: if (!_resolved)
    _resolvePresence()
  Connections {
    target: waves
    // A browse shelf builds this strip on every card and names only the
    // artists, so the ones that will never show must not run a handler
    // per card per committed batch of a running scan.
    enabled: arb.artistName !== ""
    function onLibraryPresenceChanged() {
      arb._resolvePresence()
    }
  }
  visible: !!(presence && presence.present)
  // The badge hides at the top, so nothing inside it ever sees a
  // visibility change of its own.
  opacity: arb.visible ? 1 : 0
  // Arriving is animated; being there is not. The build flags alone were
  // not enough: they only cover a fresh search or Browse build, so coming
  // BACK to a page (or a row recycling under a scroll) faded every badge
  // in a beat behind its artwork, which read as the page assembling
  // itself in front of you. _settled is the real question, and it is
  // false for exactly as long as this badge has not yet answered for the
  // artist it is showing.
  Behavior on opacity {
    enabled: arb._settled && !host.searchBuilding && !host.browseBuilding
    NumberAnimation {
      duration: 180
      easing.type: Easing.OutQuad
    }
  }
  readonly property int albums: presence ? (presence.albums || 0) : 0
  readonly property int tracks: presence ? (presence.tracks || 0) : 0
  readonly property string albumLine: arb.albums + (arb.albums === 1 ? " ALBUM" : " ALBUMS")
  readonly property string songLine: arb.tracks + (arb.tracks === 1 ? " SONG" : " SONGS")

  // THE STRIP. It sits ON the cover's lower edge over the same gradient
  // the hero card already uses to carry a caption over artwork, so the
  // words have a floor without the photograph gaining an edge: nothing to
  // align, it melts into whatever is behind it.
  Item {
    visible: arb.bar
    anchors.fill: parent

    Rectangle {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      // Taller than the words it carries, and by a lot: a scrim the
      // height of its own text is a dark bar with soft edges, not a
      // fade. The overflow is drawn inside the Art, which clips, so
      // it can reach as far up the cover as it needs to.
      height: parent.height * 2.1
      // Weighted so the words' own band is already dark and only the
      // reach above it is doing the fading: a linear ramp puts its
      // midpoint under the text, which is where a bright cover wins.
      gradient: Gradient {
        GradientStop {
          position: 0
          color: "transparent"
        }
        GradientStop {
          position: 0.42
          color: "#8f0b0d10"
        }
        GradientStop {
          position: 0.62
          color: "#e00b0d10"
        }
        GradientStop {
          position: 1
          color: "#fa0b0d10"
        }
      }
    }

    // THE STRIP'S WORDS. Every one of them carries a one-pixel black
    // outline: not a shadow and not a plate, it costs no space and
    // changes no colour, and it is the difference between text that
    // survives a blown-out white studio cover and text that has to be
    // hunted for. Centred, because a strip that spans the cover has no
    // side to favour.
    Column {
      anchors.centerIn: parent
      spacing: 2
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: "IN LIBRARY"
        color: green
        style: Text.Outline
        styleColor: "#000000"
        font.family: mono
        font.pixelSize: arb.barLabelPx
        font.bold: true
        font.letterSpacing: 1.4
      }
      Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 7
        Text {
          textFormat: Text.PlainText
          text: arb.albumLine
          color: textHi
          style: Text.Outline
          styleColor: "#000000"
          font.family: mono
          font.pixelSize: arb.barCountPx
          font.bold: true
        }
        Text {
          textFormat: Text.PlainText
          text: "\u00b7"
          color: textLo
          style: Text.Outline
          styleColor: "#000000"
          font.family: mono
          font.pixelSize: arb.barCountPx
        }
        Text {
          textFormat: Text.PlainText
          text: arb.songLine
          color: textHi
          style: Text.Outline
          styleColor: "#000000"
          font.family: mono
          font.pixelSize: arb.barCountPx
          font.bold: true
        }
      }
    }
  }

  // THE PAGE FORM. The artist page header has no cover for a strip to sit
  // on, and nothing there should be riding the photograph anyway. So it
  // is the strip's own typography with the strip taken away: the spaced
  // green label over the counts, left aligned, standing on the page.
  // No plate, no border, no fill, and no outline either: on a page the
  // background is known, so there is nothing for the words to survive.
  //
  // It sits under the artist name and above the button that would add to
  // what it counts.
  Column {
    id: abPlate
    visible: !arb.bar
    spacing: 3
    Text {
      textFormat: Text.PlainText
      text: "IN LIBRARY"
      color: green
      font.family: mono
      font.pixelSize: 10
      font.bold: true
      font.letterSpacing: 1.4
    }
    Row {
      spacing: 8
      Text {
        textFormat: Text.PlainText
        text: arb.albumLine
        color: textHi
        font.family: mono
        font.pixelSize: 15
        font.bold: true
      }
      Text {
        textFormat: Text.PlainText
        text: "\u00b7"
        color: textDim
        font.family: mono
        font.pixelSize: 15
      }
      Text {
        textFormat: Text.PlainText
        text: arb.songLine
        color: textHi
        font.family: mono
        font.pixelSize: 15
        font.bold: true
      }
    }
  }
}

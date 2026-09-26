import QtQuick
import "primitives" as Primitives

// Art-first Browse card (the streaming-service look): the artwork IS the
// card, no frame, quiet caption beneath, download surfacing only on hover
// (or while it carries live download state). hero:true renders the big
// top-shelf variant with the caption overlaid on a bottom scrim.
// `host` is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load.
// It reads through it:
//   host.browseCardDownload / host.browseCardOpenable / host.dlSt / host.hoverPrefetch /
//   host.hoverPrefetchCancel / host.libStamp / host.openBrowseCard /
//   host.openLibraryClaim / host.openRedownloadGate / host.ownAnswers /
//   host.ownCardForget / host.ownCardRegister / host.ownGen / host.ownKeys /
//   host.pvSt / host.togglePreview
// The palette values are local copies of Main.qml's static literals, except accent which binds to Primitives.Palette —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Item {
  id: ac
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — accent binds to Primitives.Palette; the rest are copies of Main.qml's static literals.
  readonly property color accent: Primitives.Palette.accent   // phosphor green (primary)
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property real btnBorderW: 1.5
  readonly property int btnRad: 8              // button corner radius
  readonly property real btnTrack: 0              // label letter-spacing
  readonly property color cyan: "#56c8d8"   // HIGH tier + queued
  readonly property color cyanDim: "#3a8d99"
  readonly property color gold: "#ffb01f"   // HI-RES / VIDEO tier + meter mid band
  readonly property color goldDim: "#b07d18"
  readonly property color green: "#3ef08a"   // LOSSLESS tier + done state
  readonly property color greenDim: "#2aa862"
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)

  property var card: ({})
  property bool hero: false
  readonly property string kind: card.kind || ""
  readonly property real artSize: hero ? 280 : 200
  width: artSize
  height: hero ? artSize : artSize + 46
  // Whether the art and title offer the card's page is Main.qml's
  // browseCardOpenable verdict, the same one the click path reads, so the
  // cursor and the click can never disagree.
  readonly property bool openable: host.browseCardOpenable(ac.card)
  // Prefetch arms from the whole card, title and caption included, the
  // way BrowseCard's does. Its own handler: the artwork's acWrapHover
  // also drives the hover strip and the corner icon, which must stay
  // tied to the art alone.
  HoverHandler {
    onHoveredChanged: hovered ? host.hoverPrefetch(ac.card) : host.hoverPrefetchCancel(ac.card)
  }
  // The library verdict this card carries lives in LibraryVerdict, the
  // one owner both card styles share; the aliases below keep this card's
  // public surface (what the strip, the pill and the scenarios read).
  LibraryVerdict {
    id: acVerdict
    host: ac.host
    card: ac.card
  }
  readonly property var libPresence: acVerdict.presence
  readonly property bool libPresent: acVerdict.present
  readonly property bool libFull: acVerdict.full
  readonly property bool libSure: acVerdict.sure
  readonly property bool libAtmos: acVerdict.atmos
  readonly property string libState: acVerdict.state
  readonly property bool libClaim: acVerdict.claim
  readonly property string libWord: acVerdict.word
  // The cross-session downloaded fact, the same rollup the full button
  // uses: every member track recorded by a real download and still up
  // to date. Session state (host.dlSt) only lives until quit; this is
  // what lets a card still say DOWNLOADED tomorrow. Collections only:
  // membership is recorded per collection id, and it is one cached
  // bridge call per card, the same budget the library verdict spends.
  readonly property bool ownable: ac.kind === "album" || ac.kind === "playlist" || ac.kind === "mix"
  property bool owned: false
  // Member ids from the last rollup, kept so the ownership listener can
  // ignore answers about other collections' tracks: at launch every
  // cold query announces its first answer, and a grid of cards each
  // re-rolling on every one of them is a signal storm on the GUI
  // thread that turns the launch animation jumpy.
  property var _ownIds: null
  // Batch keys for those members (host.ownKeys).
  property var _ownKeys: null
  function applyOwn(co) {
    var ids = co ? co.ids : null
    _ownIds = ids
    _ownKeys = host.ownKeys(ids)
    host.ownCardRegister("" + (ac.card.id || ""), _ownKeys)
    var v = co ? co.verdict : "no"
    if (v === "no") {
      owned = false
      return
    }
    // Cold answers in flight and nothing firmly against: keep the last
    // known word rather than flashing the strip through DOWNLOAD; the
    // ownership nudge re-asks once the truth lands.
    if (v === "owned")
      owned = true
  }
  function refreshOwned(live) {
    if (!ac.ownable) {
      owned = false
      return
    }
    // One bridge call for the whole collection (member ids + verdict):
    // a call per member was ~15 interpreter round-trips per card, and
    // under the launch-time scan each of them queued for its turn.
    // None at all while the card is created: the payload's own
    // rollup (card.own) answers, see LibraryVerdict. And none per
    // card when a batch of answers lands: the root asks once for
    // every hit card (ownCardsBatch) and the card reads its answer.
    applyOwn((!live && ("own" in ac.card) && ac.card.ownGen === host.ownGen) ? ac.card.own : waves.collectionOwnership("" + (ac.card.id || "")))
  }
  Component.onDestruction: host.ownCardForget("" + (ac.card.id || ""))
  onCardChanged: refreshOwned(false)
  Component.onCompleted: refreshOwned(false)
  Connections {
    target: waves
    enabled: ac.ownable
    // Empty id = broadcast (the quality setting changed). Only this
    // card's own members matter, and a burst of member answers (an
    // album's cold queries all landing) coalesces into one rollup.
    function onOwnershipChanged(tid) {
      if (tid === "" || (ac._ownIds && ac._ownIds.indexOf(tid) !== -1))
        acOwnCoalesce.restart()
    }
    function onCollectionMembershipChanged(cid) {
      if (cid === "" + (ac.card.id || ""))
        ac.refreshOwned(true)
    }
  }
  Connections {
    target: ac.host
    enabled: ac.ownable
    function onOwnAnswersGenChanged() {
      var a = host.ownAnswers["" + (ac.card.id || "")]
      if (a)
        ac.applyOwn(a)
    }
  }
  Timer {
    id: acOwnCoalesce
    interval: 50
    onTriggered: ac.refreshOwned(true)
  }
  // Downloaded this session, recorded as downloaded, or a full copy on
  // disk: the NEW mark on the caption stops breathing.
  readonly property bool haveIt: ac.owned || ac.libFull || host.dlSt(ac.card.id || "") === "done"
  Art {
    id: acArt
    host: ac.host
    width: ac.artSize
    height: ac.artSize
    radius: 12
    // Heroes tilt too: the landing's first shelf renders through the
    // hero card, and it would sit flat while every card around it moves.
    // The on-art caption and scrim are children of the art, so they ride
    // the same tilt.
    hoverFx: true
    // Videos have no audio-preview path, so they never take the raise.
    fxKind: ac.kind === "video" ? "" : ac.kind
    fxId: ac.kind === "video" ? "" : ("" + (ac.card.id || ""))
    url: ac.card.art || ""
    // Declared first so the hover controls' own MouseAreas sit above it:
    // the artwork opens the page, the buttons keep their clicks.
    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: ac.openable ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: host.openBrowseCard(ac.card)
    }
    // hero caption rides ON the art over a bottom scrim (children are
    // clipped to the rounded rect, so the scrim keeps the corners)
    Rectangle {
      // scrim yields to the hover controls so they never overlap the caption
      visible: ac.hero && opacity > 0
      opacity: acArt.controlsOn ? 0 : 1
      Behavior on opacity {
        NumberAnimation {
          duration: 160
          easing.type: Easing.OutQuad
        }
      }
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      height: 96
      gradient: Gradient {
        GradientStop {
          position: 0
          color: "transparent"
        }
        GradientStop {
          position: 1
          color: "#e60b0d10"
        }
      }
    }
    Column {
      id: acHeroCap
      // Named so the scenario test can prove the artist strip stacks
      // ABOVE this caption rather than back onto its edge.
      objectName: "acHeroCaption"
      visible: ac.hero && opacity > 0
      opacity: acArt.controlsOn ? 0 : 1
      Behavior on opacity {
        NumberAnimation {
          duration: 160
          easing.type: Easing.OutQuad
        }
      }
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      anchors.margins: 14
      spacing: 3
      Text {
        textFormat: Text.PlainText
        text: ac.card.title || ""
        color: "#f2f4f7"
        font.pixelSize: 16
        font.bold: true
        width: parent.width
        elide: Text.ElideRight
      }
      CardCaption {
        host: ac.host
        card: ac.card
        px: 12
        metaColor: "#f2f4f7"
        width: parent.width
        settled: ac.haveIt
      }
    }
    // The library pill, top-left over the art: the one corner no
    // caption or hover control uses. Unlike the strip it does NOT wait
    // for a hover, which is the whole reason it is here: a shelf of
    // cards has to answer "what do I already have" at a glance, and
    // the strip only appears under the cursor. Fed from the card's own
    // resolved verdict rather than AlbumPresencePill, which would ask
    // the same question a second time per card.
    LibraryTag {
      host: ac.host
      visible: ac.libPresent
      settleKey: "" + (ac.card.id || "")
      x: 10
      y: 10
      have: ac.libPresence ? (ac.libPresence.local_tracks || 0) : 0
      total: ac.card.tracks || 0
      declared: ac.libPresence ? (ac.libPresence.local_declared || 0) : 0
      albumId: ac.libPresence ? (ac.libPresence.local_album_id || "") : ""
      qclass: ac.libPresence ? (ac.libPresence.local_class || "") : ""
      proven: ac.libSure
    }
    // The Atmos micro-badge (§8.4): the copy holds Dolby Atmos
    // Versions beside its canonical set. Under the library pill, the
    // one corner no caption or hover control uses; absolutely placed,
    // so it can never move the art or the caption, and hidden
    // libraries never take this branch.
    Text {
      visible: ac.libPresent && ac.libAtmos
      textFormat: Text.PlainText
      text: "ATMOS TOO"
      x: 10
      y: 32
      color: textDim
      font.family: mono
      font.pixelSize: 9
      font.bold: true
    }
    // The artist answer to the pill above, for the same reason: a shelf
    // of artists has to say "what do I already have" at a glance. It
    // resolves itself off the rollup rather than the album verdict,
    // which is null for every non-album card, and it takes the cover's
    // lower edge rather than the pill's corner because a rollup is two
    // lines and a face is usually in the middle.
    ArtistBadges {
      host: ac.host
      bar: true
      width: parent.width
      // A hero carries its own caption on the cover's bottom edge,
      // so the strip STACKS above it instead of standing down.
      // Standing down would make the biggest card on the landing's
      // first shelf the one card there that cannot say what you
      // already hold, the opposite of what that card is for.
      // Nothing about the strip needs the very edge: it is a
      // gradient that melts into whatever is behind it, so it gets
      // its floor wherever it is put.
      anchors.bottom: ac.hero ? acHeroCap.top : parent.bottom
      anchors.bottomMargin: ac.hero ? 2 : 0
      // Gated by the NAME, never by an outer visible binding: the
      // badge hides itself when the rollup says nothing, and
      // overriding `visible` here would replace that with an
      // always-shown strip.
      artistName: ac.kind === "artist" ? ("" + (ac.card.name || ac.card.title || "")) : ""
    }
    // Hover controls. Collections (album / playlist / mix) get the
    // full stacked pair on the art, Preview (a random track for
    // playlists/mixes) over Download; other kinds keep the corner icon.
    readonly property bool collection: ac.kind === "album" || ac.kind === "playlist" || ac.kind === "mix"
    readonly property string kindLabel: ac.kind === "album" ? "album" : ac.kind === "playlist" ? "playlist" : "mix"
    readonly property bool controlsOn: collection && (acWrapHover.hovered || host.dlSt(ac.card.id || "") !== "" || host.pvSt(ac.kind, ac.card.id || "") !== "")
    // The artwork's own hover: the strip, the percentage word and the
    // corner icon follow it. Prefetch is NOT wired here, it rides the
    // card-wide handler on ac, so moving the pointer from the art down
    // to the title does not cancel a dwell that is still on the card.
    HoverHandler {
      id: acWrapHover
    }
    RiseIn {
      id: acRiser
      host: ac.host
      on: acArt.controlsOn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      anchors.margins: 10
      height: acSwap.implicitHeight
      readonly property string acPvSt: host.pvSt(ac.kind, ac.card.id || "")
      readonly property string acDlSt: host.dlSt(ac.card.id || "")
      // A finished download is not a live control: it goes back to
      // the split strip, whose download half reads the checkmark
      // and DOWNLOADED, so Preview stays one click away instead of
      // being evicted by a full-width done pill for the session.
      // Session state OR the ownership rollup: this session's done
      // and last week's download must wear the same word. A LIVE
      // state (queued, running, failed) outranks the rollup, so a
      // re-download of an owned album still shows its progress.
      readonly property bool dlDone: acDlSt === "done" || (acDlSt === "" && ac.owned)
      // Idle strip and live controls are the same pill: it rolls its
      // contents over and stretches to the arriving side's size, in both
      // directions, for a preview and for a download alike.
      RollSwap {
        id: acSwap
        host: ac.host
        anchors.horizontalCenter: parent.horizontalCenter
        live: acRiser.acPvSt !== "" || (acRiser.acDlSt !== "" && !acRiser.dlDone)
        // The pill draws the live side's fill AND outline (a download
        // button is a filled control, and a bare one paints neither):
        // one rectangle, so the fill can never cover the border ring.
        liveColor: acLive.dlOn ? acDl.fill : idleColor
        liveBorder: acLive.dlOn ? acDl.edge : (acRiser.acPvSt === "error" ? red : accentDim)
        // The idle pill's outline comes with the verdict too, so the
        // two halves read as one control in one mood rather than a
        // coloured half bolted into an accent frame.
        idleBorder: acStrip.stEdge
        liveItem: Column {
          id: acLive
          spacing: 6
          readonly property bool pvOn: acRiser.acPvSt !== ""
          readonly property bool dlOn: acRiser.acDlSt !== "" && !acRiser.dlDone
          // Full width while a full-width row is showing; a finished
          // or failed download goes back to hugging its label, the
          // way inline buttons do everywhere else.
          width: (pvOn || acDl.st === "running") ? acRiser.width : acDl.implicitWidth
          // Live preview: the full scrubber bar (same one as everywhere else)
          PreviewBar {
            host: ac.host
            visible: acLive.pvOn
            bare: true
            width: parent.width
            height: implicitHeight
            kind: ac.kind
            pid: ac.card.id || ""
            label: "Preview " + acArt.kindLabel
          }
          // Live download: the full dot-matrix progress bar / done / retry
          DownloadButton {
            id: acDl
            host: ac.host
            visible: acLive.dlOn
            bare: true
            anchors.horizontalCenter: parent.horizontalCenter
            width: st === "running" ? parent.width : implicitWidth
            mediaId: ac.card.id || ""
            chooserKind: ac.card.kind || "album"
            // No ownership rollup here: this button is visible only
            // while a LIVE download state exists, and live state always
            // outranks the owned rollup, so the rollup's result could
            // never render. Computing it per card was pure cost.
            collectionCheck: false
            label: "Download " + acArt.kindLabel
            // The percentage carves in while the CARD is hovered,
            // not just the pill: the pill rose for the card's hover
            // in the first place, and a pointer anywhere on the art
            // is already asking about this download.
            wordHover: acWrapHover.hovered
            onTap: function () {
              host.browseCardDownload(ac.card)
            }
          }
        }
        // Idle: the slim strip, ▶ PREVIEW | ⭳ DOWNLOAD in one thin pill
        idleItem: Item {
          id: acStrip
          width: acStripRow.implicitWidth
          height: 30
          // The verdict, in the tier colours the library pill uses,
          // so the two things a card now says (the pill's what you
          // have, the half's what a click will do) never disagree
          // about what a colour means. Unlike the full download
          // button this half stays UNFILLED: the strip is a thin
          // outlined control riding on artwork, and filling one half
          // of it made a solid block of a shape whose whole job is to
          // stay out of the way of the cover. So the lettering
          // carries it, which is why proven reads in the pill's
          // lossless green rather than the filled button's accent:
          // the accent is already on PREVIEW, one divider away.
          // A download Waves made is the freshest fact the half can
          // state: it wears the checkmark and the fact green ahead
          // of any library verdict (a gold MAYBE over a file Waves
          // itself wrote would be absurd), and its click opens the
          // owned gate with REDOWNLOAD one click away.
          readonly property bool dlDone: acRiser.dlDone
          readonly property color stInk: dlDone ? green : ac.libState === "proven" ? green : ac.libState === "maybe" ? gold : ac.libState === "partial" ? cyan : accent
          readonly property color stEdge: dlDone ? greenDim : ac.libState === "proven" ? greenDim : ac.libState === "maybe" ? goldDim : ac.libState === "partial" ? cyanDim : accentDim
          // Ninety pixels of half, so the full button's wording
          // ("PARTIALLY IN LIBRARY") cannot ride here. The words are the
          // verdict's own shortest forms; a finished download wears
          // DOWNLOADED ahead of any of them.
          readonly property string stWord: acStrip.dlDone ? "DOWNLOADED" : ac.libWord
          // The strip is sized by its own words and nothing capped it
          // against the cover it rides on, so the long ones outgrew
          // the artwork, which clips, and lost their first and last
          // letters at both ends (the pill is centred). On the
          // ordinary 200px card DOWNLOADED ran 7px past the cover,
          // and the everyday DOWNLOAD and IN LIBRARY closed to within
          // 5px of its edge, having already overrun the 10px-inset
          // slot the live controls sit in. The words are the shortest
          // forms that still say which state is true, so the room
          // comes out of the padding instead: each half keeps its
          // full 20 until the strip would not fit, then gives up as
          // much as it must, down to a floor that still reads as a
          // button. Measured against the ART, not that inset slot:
          // the pill may come within 6px of the cover's edge, which
          // is where the last few pixels come from.
          readonly property real padFull: 20
          readonly property real padMin: 8
          readonly property real availW: acArt.width - 12
          readonly property real naturalW: acStripPv.implicitWidth + acStripDl.implicitWidth + btnBorderW + 2 * padFull
          // Halved because both halves give the same amount up, which
          // keeps the divider where the words put it.
          readonly property real pad: naturalW <= availW ? padFull : Math.max(padMin, padFull - (naturalW - availW) / 2)
          // Hover swell: one handler split by x (the halves' own
          // MouseAreas would steal the hover), so crossing the
          // divider hands the light over without a gap. Where PREVIEW
          // ends is the real divider, not the midpoint, and its
          // region runs one border-width past it so the lit edge
          // swallows the dim divider instead of sitting beside it.
          HoverHandler {
            id: acStripHover
          }
          readonly property real dividerX: acStripRow.children[0].width
          readonly property real hoverX: acStripHover.point.position.x
          HoverSwell {
            z: 1    // above the Row, so the lit edge covers the divider
            width: acStrip.dividerX + btnBorderW
            height: acStrip.height
            radR: 0
            on: acStripHover.hovered && acStrip.hoverX <= acStrip.dividerX
          }
          HoverSwell {
            z: 1
            x: acStrip.dividerX
            width: acStrip.width - acStrip.dividerX
            height: acStrip.height
            radL: 0
            // The lit edge takes the verdict's own colour, so
            // hovering a claimed half does not flash accent green
            // over a gold or cyan control.
            tone: acStrip.stInk
            on: acStripHover.hovered && acStrip.hoverX > acStrip.dividerX
          }
          Row {
            id: acStripRow
            anchors.verticalCenter: parent.verticalCenter
            Item {
              implicitWidth: acStripPv.implicitWidth + acStrip.pad
              implicitHeight: 30
              Row {
                id: acStripPv
                anchors.centerIn: parent
                spacing: 6
                Ico {
                  name: "play"
                  color: accent
                  size: 11
                  anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                  textFormat: Text.PlainText
                  text: "PREVIEW"
                  color: accent
                  font.family: uiFont
                  font.pixelSize: 10
                  font.bold: true
                  font.letterSpacing: btnTrack
                  anchors.verticalCenter: parent.verticalCenter
                }
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: host.togglePreview(ac.kind, ac.card.id || "", 0)
              }
            }
            Rectangle {
              width: btnBorderW
              height: 30
              color: acStrip.stEdge
              anchors.verticalCenter: parent.verticalCenter
            }
            Item {
              implicitWidth: acStripDl.implicitWidth + acStrip.pad
              implicitHeight: 30
              Row {
                id: acStripDl
                anchors.centerIn: parent
                spacing: 6
                Ico {
                  name: (acStrip.dlDone || ac.libClaim) ? "check" : "arrow-down"
                  color: acStrip.stInk
                  size: (acStrip.dlDone || ac.libClaim) ? 14 : 12
                  bold: 10
                  anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                  textFormat: Text.PlainText
                  text: acStrip.stWord
                  color: acStrip.stInk
                  font.family: uiFont
                  font.pixelSize: 10
                  font.bold: true
                  font.letterSpacing: btnTrack
                  anchors.verticalCenter: parent.verticalCenter
                }
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                // A finished download opens the owned gate:
                // the fact, then REDOWNLOAD one click away. A
                // full claim opens the claim gate, the same
                // click the full button gives it. A partial
                // copy downloads: with the bulk skip gate on,
                // that fetches the rest.
                onClicked: {
                  if (acStrip.dlDone) {
                    host.openRedownloadGate(ac.card)
                    return
                  }
                  if (ac.libClaim)
                    host.openLibraryClaim(ac.card.id || "", "" + (ac.card.title || ""), "" + (ac.libPresence.local_album_id || ""))
                  else
                    host.browseCardDownload(ac.card)
                }
              }
            }
          }
        }
      }
    }
    RiseIn {
      host: ac.host
      on: !acArt.collection && (acWrapHover.hovered || host.dlSt(ac.card.id || "") !== "")
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      anchors.margins: 10
      width: 38
      height: 36
      Rectangle {
        anchors.fill: parent
        radius: btnRad
        color: "#d90d0f12"
        DownIcon {
          host: ac.host
          anchors.centerIn: parent
          mediaId: ac.card.id || ""
          // This corner icon renders only for NON-collection kinds
          // (collections get the stacked controls above), so a
          // collection rollup here could never be seen; leaving it
          // on ran two membership rollups per collection card.
          collectionCheck: false
          onTap: function () {
            host.browseCardDownload(ac.card)
          }
        }
      }
    }
  }
  Column {
    visible: !ac.hero
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: acArt.bottom
    anchors.topMargin: 8
    spacing: 2
    Text {
      id: acTitle
      textFormat: Text.PlainText
      text: ac.card.title || ""
      color: textHi
      font.pixelSize: 13
      font.bold: true
      width: parent.width
      elide: Text.ElideRight
      horizontalAlignment: ac.kind === "artist" ? Text.AlignHCenter : Text.AlignLeft
      font.underline: acTitleMa.containsMouse && ac.openable
      MouseArea {
        id: acTitleMa
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: ac.kind === "artist" ? parent.horizontalCenter : undefined
        anchors.left: ac.kind === "artist" ? undefined : parent.left
        width: Math.min(parent.implicitWidth, parent.width)
        hoverEnabled: true
        cursorShape: ac.openable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: host.openBrowseCard(ac.card)
      }
    }
    CardCaption {
      host: ac.host
      card: ac.card
      px: 11
      center: ac.kind === "artist"
      width: parent.width
      settled: ac.haveIt
    }
  }
}

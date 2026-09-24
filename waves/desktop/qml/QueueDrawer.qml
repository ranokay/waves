import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// The download queue drawer: one sectioned ListView over the app's queue
// model (grouped headers, per-row status/progress/quality, the expanded
// track ledger), plus the drag handle on its edge that sets the remembered
// width.
// 'host' is Main.qml's root object, bound at every instantiation and
// required so a missed binding fails at load. The drawer reads through it:
//   host.height / host.width      the window bounds it spans
//   host.queueWidth               the remembered width (the grip writes it)
//   host.activeQueueCount / host.queueTracks / host.queueExpanded /
//     host.completedCollapsed / host.queueLedgerMax / host.queueLedgerPeek
//     the queue state the rows render
//   host.pulseSection / host.pulseTick / host.ledPulse / host.shimmerPhase /
//     host.queueEdgeHeld  the shared section-pulse and light clocks
//   host.tierFloor / host.queueTrackTier / host.queueSectionWord /
//     host.queueGroupCount / host.retryableStatus / host.statusColor /
//     host.qualFg  the row vocabulary helpers
// Its `queueModel` is the app's queue model, bound at the instantiation and
// required for the same reason.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Drawer {
  id: queueDrawer
  required property var host
  required property var queueModel
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentContTx: "#86ffaa"   // text on accent container
  readonly property color accentSoft: "#9dffbe"   // CRT flash / phosphor highlight
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color cyanDim: "#3a8d99"
  readonly property color divider: "#22262d"
  readonly property color greenCont: "#08230f"
  readonly property color greenDim: "#2aa862"
  readonly property color libAccent: "#e5a00d"
  readonly property color line1: "#22262d"   // row dividers
  readonly property string mono: monoFont   // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color redContTx: "#ff9d97"
  readonly property color redDim: "#b23f3a"   // small-lossy pill border
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color surface2: "#191c22"   // hover / nested
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"
  // 420, not the 340 it shipped at: the quality a row states is the
  // element that costs the title its width, and at 340 either the tier
  // or the title had to give way. It is the floor now rather than the
  // width, since the handle below drags it wider, and the clamp is
  // re-read here so shrinking the window pulls an over-wide drawer in.
  edge: Qt.RightEdge
  height: host.height
  width: Math.max(420, Math.min(host.width - 80, host.queueWidth))
  background: Rectangle {
    color: surface
    border.color: line1
  }
  ColumnLayout {
    anchors.fill: parent
    anchors.margins: 16
    spacing: 12
    RowLayout {
      Layout.fillWidth: true
      Text {
        text: "Download queue"
        color: textHi
        font.pixelSize: 16
        font.bold: true
      }
      Item {
        Layout.fillWidth: true
      }
      // Pause / resume all. Gold while running (pausing interrupts but
      // loses nothing), green once paused, where RESUME is the way
      // forward. Both are SpecBtn, so the fill, the border and the
      // hover lift are the exit prompt's, not a local imitation.
      SpecBtn {
        id: queuePauseBtn
        visible: queueModel.count > 0
        warn: !waves.paused
        primary: waves.paused
        label: waves.paused ? "RESUME" : "PAUSE"
        onClicked: waves.paused ? waves.resumeQueue() : waves.pauseQueue()
      }
      // Stop everything: abort running downloads and the queued
      // ones; the rows stay, as Stopped, with RETRY. One click, always:
      // it is the panic control. The screen-reader name says what the
      // click will end, since the visible word stays the short one.
      SpecBtn {
        // Or a scan in flight: it has no row yet, and this is
        // the only control that ends it.
        visible: host.activeQueueCount > 0 || waves.scanning
        danger: true
        label: "STOP"
        accessibleLabel: host.activeQueueCount === 0 ? "Stop the scan, nothing queued yet" : host.activeQueueCount === 1 ? "Stop 1 download, the row stays for retry" : "Stop " + host.activeQueueCount + " downloads, rows stay for retry"
        onClicked: waves.stopAll()
      }
      // Shut the drawer. Clicking the page behind it already does
      // this, but that is a gesture you have to know: the panel needs
      // a way out you can see. Last in the row so it sits in the
      // corner every window puts a close in, and always there, since
      // an empty queue (where PAUSE and STOP are both gone) is
      // exactly when the way out is hardest to guess.
      SpecBtn {
        id: queueCloseBtn
        icon: "close"
        accessibleLabel: "Close queue"
        onClicked: queueDrawer.close()
      }
    }
    Text {
      textFormat: Text.PlainText
      text: queueModel.count + (queueModel.count === 1 ? " item" : " items")
      color: textLo
      font.family: mono
      font.pixelSize: 12
    }
    ListView {
      id: queueList
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      spacing: 0
      model: queueModel
      ScrollBar.vertical: ScrollBar {}

      // Grouped sections: Completed (collapsible) · Failed · Stopped · Downloading · Queued
      section.property: "uiGroup"
      section.criteria: ViewSection.FullString
      section.delegate: Item {
        id: secItem
        // Named so a scenario can find the headers and prove which
        // one the count pulse lands on.
        objectName: "queueSectionHeader"
        required property string section
        width: ListView.view.width
        // Two extra pixels of headroom so the header's chips are not
        // squeezed against the rows above and below them.
        implicitHeight: 34
        RowLayout {
          anchors.fill: parent
          anchors.topMargin: 8
          anchors.bottomMargin: 4
          anchors.leftMargin: 2
          anchors.rightMargin: 2
          spacing: 8
          // Above the header-wide collapse MouseArea below, so the
          // per-section CLEAR gets the click. Plain Text does not
          // consume events, so collapsing still works everywhere else.
          z: 3
          Ico {
            visible: secItem.section === "completed"
            name: "check"
            color: accent
            size: 13
            Layout.alignment: Qt.AlignVCenter
          }
          Text {
            id: secLbl
            textFormat: Text.PlainText
            text: host.queueSectionWord(secItem.section).toUpperCase() + " · " + host.queueGroupCount(secItem.section)
            // Brightness tracks how live the section is: the work
            // happening right now reads near-white, what is only
            // waiting stays dim, so the eye lands on Downloading
            // first when the drawer opens.
            // The three settled sections carry a colour each:
            // Completed the soft green, Failed the hot red,
            // Stopped the soft red, still red (work you ended,
            // not work that finished) but a step softer than
            // a failure so the two never read as one.
            color: secItem.section === "completed" ? accentContTx : secItem.section === "failed" ? red : secItem.section === "stopped" ? redContTx : secItem.section === "downloading" ? textHi : textDim
            font.family: mono
            font.pixelSize: 10
            font.bold: true
            font.letterSpacing: 1.4
            Layout.alignment: Qt.AlignVCenter
          }
          Rectangle {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            height: 1
            color: divider
          }
          // One-click retry of every row in the section, riding
          // the Failed and Stopped headers themselves so it appears
          // exactly when it applies and takes no room anywhere
          // else. Each header retries its own section only.
          SpecBtn {
            compact: true
            primary: true
            label: "RETRY ALL"
            accessibleLabel: "Retry all " + host.queueSectionWord(secItem.section) + " downloads"
            visible: secItem.section === "failed" || secItem.section === "stopped"
            Layout.alignment: Qt.AlignVCenter
            onClicked: {
              if (secItem.section === "failed")
                waves.retryAllFailed()
              else
                waves.retryAllStopped()
            }
          }
          // Every section clears itself. Riding the header means
          // the scope needs no spelling out (it takes the section
          // it sits on), so the control stays one short word in
          // that section's own colour instead of a grey footer
          // button that has to name what it sweeps. Downloading
          // has none: stopping a live transfer is the row's own
          // control, never a bulk one.
          // The three destructive ones (Failed, Stopped, Queued)
          // arm first: the first click says SURE? and clears
          // nothing, the second clears, letting the window lapse
          // disarms. Completed is tidy-up and stays one click.
          SpecBtn {
            id: clearBtn
            objectName: "queueClearBtn"
            compact: true
            // Completed is tidy-up, so it takes the green
            // recipe; the other three discard work you asked
            // for, which is the danger red the exit prompt uses.
            primary: secItem.section === "completed"
            danger: secItem.section !== "completed"
            label: secItem.clearArmed && secItem.section !== "completed" ? "SURE?" : "CLEAR"
            accessibleLabel: (secItem.clearArmed && secItem.section !== "completed" ? "Confirm clearing " : "Clear ") + host.queueSectionWord(secItem.section) + " downloads"
            visible: secItem.section !== "downloading"
            Layout.alignment: Qt.AlignVCenter
            onClicked: {
              if (secItem.section === "completed") {
                waves.clearFinished()
                return
              }
              if (!secItem.clearArmed) {
                secItem.clearArmed = true
                clearDisarm.restart()
                return
              }
              secItem.clearArmed = false
              clearDisarm.stop()
              if (secItem.section === "failed")
                waves.clearFailed()
              else if (secItem.section === "stopped")
                waves.clearStopped()
              else
                waves.clearQueued()
            }
          }
          // The armed window: lapse it and the button is CLEAR again,
          // the queue untouched. Three seconds is long enough to mean
          // it and short enough that a stale SURE? never waits.
          Timer {
            id: clearDisarm
            interval: 3000
            onTriggered: secItem.clearArmed = false
          }
          Text {
            textFormat: Text.PlainText
            visible: secItem.section === "completed"
            text: host.completedCollapsed ? "▸" : "▾"
            color: accent
            font.pixelSize: 11
            Layout.alignment: Qt.AlignVCenter
          }
        }
        MouseArea {
          anchors.fill: parent
          enabled: secItem.section === "completed"
          cursorShape: Qt.PointingHandCursor
          onClicked: host.completedCollapsed = !host.completedCollapsed
        }
        // Armed, not fired: the tick lands mid-move, while the
        // view is still handing headers to their new sections, so
        // every header waits a frame and then asks whether IT is
        // the section that grew. A header re-sectioned mid-pulse
        // drops the animation rather than carrying it across.
        // A section gaining its FIRST row is covered by this too,
        // by the same two properties. The tick arms every header
        // that exists NOW, the view then hands one of those pooled
        // headers to the brand new section, and the timer fires
        // afterwards and asks what section it is holding by then.
        // So the header that pulses need never have existed when
        // the count moved.
        // The handoff can also land AFTER the arm fired: the
        // instance holding the section when the tick arrived
        // starts the pulse and is then re-sectioned away, dropping
        // it, while the instance that receives the section has
        // already asked and declined. So a section change into the
        // pulse section arms again, under two guards: secArmedTick
        // is the tick this instance was armed for, so a change
        // re-arms only a header armed for the current tick (a
        // header created later never armed, and one whose last arm
        // is an older tick stays still, so no rise plays on a
        // header that was not part of it), and secPulsedTick is
        // the tick this instance already pulsed, so one rise never
        // fires the animation twice on one header. Arming on
        // Component.onCompleted instead guards nothing: the
        // first-row case is served by the pool, as
        // tests/ui/test_queue_section_pulse.py pins.
        property int secPulsedTick: 0
        property int secArmedTick: -1
        // The CLEAR confirm gate: first click arms (SURE?), second
        // clears. Reset on re-section like the pulse above — a pooled
        // header must never carry another section's armed click.
        property bool clearArmed: false
        // Whether this header holds the section that rose and has
        // not pulsed for the current tick yet.
        function secPulseDue() {
          return secItem.section === host.pulseSection && secPulsedTick !== host.pulseTick
        }
        Connections {
          target: host
          function onPulseTickChanged() {
            secArmedTick = host.pulseTick
            secArm.restart()
          }
        }
        Timer {
          id: secArm
          interval: 16
          onTriggered: {
            if (secPulseDue()) {
              secPulsedTick = host.pulseTick
              secPulse.restart()
            }
          }
        }
        onSectionChanged: {
          secPulse.stop()
          secLbl.scale = 1
          clearArmed = false
          clearDisarm.stop()
          if (secArmedTick === host.pulseTick && secPulseDue())
            secArm.restart()
        }
        SequentialAnimation {
          id: secPulse
          objectName: "queueSectionPulse"
          NumberAnimation {
            target: secLbl
            property: "scale"
            to: 1.25
            duration: 150
            easing.type: Easing.OutCubic
          }
          NumberAnimation {
            target: secLbl
            property: "scale"
            to: 1.0
            duration: 180
            easing.type: Easing.OutCubic
          }
        }
      }

      delegate: Item {
        id: qrow
        required property var model
        readonly property string st: model.status
        readonly property bool isComp: model.uiGroup === "completed"
        readonly property bool collapsed: isComp && host.completedCollapsed
        readonly property bool lingering: st === "done" && !model.moved
        // Collection rows (album, playlist, mix) expand in place to
        // an ordered per-track list (live status/progress). The
        // per-track registry behind it is kept for every collection
        // job, and loadQueueTracks orders it by the collection's
        // own list; gating this to albums alone would leave a
        // playlist or mix row with no ledger and no hover peek.
        // Expansion state lives on the host (keyed by qid) so it
        // survives delegate recycling.
        // A one-item release is its own ledger: the card already
        // names the release, its tier and its progress, so a list
        // of one line is nothing a click could reveal. `tracks` is
        // the total the row was queued with (_track_count, or the
        // merge plan's length), and only an EXACT 1 opts out: 0
        // means the count was not known, which is the case that
        // still needs the ledger.
        readonly property bool expandable: model.collection === true && model.tracks !== 1
        readonly property bool single: model.collection === true && model.tracks === 1
        readonly property bool qexp: expandable && host.queueExpanded[model.qid] === true
        // A row's stops share one focusability rule: a collapsed Completed
        // row, or a row on its way out, is not on screen and keeps no stop.
        readonly property bool rowFocusable: qrow.visible && !qrow.collapsed && !qrow.leaving
        // A running or queued row's ✕ gives up the wait; a settled row's ✕
        // removes it. One read for the ✕'s styling, the ✕'s press action
        // and the row's Delete key, so the three can never disagree.
        readonly property bool live: st === "running" || st === "queued"
        // What the row is called in the accessibility tree: the drawn title
        // and artist, or the queue id when a row arrives without either (an
        // unnamed tab stop is a silent one).
        function spokenName() {
          var n = "" + (model.name || "")
          if (model.artist)
            n = n === "" ? "" + model.artist : n + " by " + model.artist
          return n === "" ? "Queue item " + model.qid : n
        }
        // Return/Enter/Space on the row. The pointer's click opens a
        // ledger, so the row's keyboard action opens it too; a settled row
        // with no ledger to open retries, the face its retry mark draws. A
        // live row answers neither (Delete gives it up).
        function rowActivate() {
          if (qrow.expandable) {
            qrow.qtoggle()
            return
          }
          if (host.retryableStatus(qrow.st))
            waves.retryQueueItem(model.qid)
        }
        // The ✕ action, shared by the pointer, the reader and Delete.
        function giveUp() {
          if (qrow.live)
            waves.cancelQueueItem(model.qid)
          else
            waves.removeQueueItem(model.qid)
        }
        // Delete gives the row up from any of the row's own stops: the key
        // bubbles up from the focused card, retry mark or give-up control to
        // the delegate, so one handler covers all three.
        Keys.onDeletePressed: function (event) {
          event.accepted = true
          qrow.giveUp()
        }
        // Hover peek: a collapsed album card dips open ~30px so the
        // track view's existence is discoverable without a click.
        // A single peeks too, and that is the point: a row that does
        // nothing at all under the pointer reads as a broken row,
        // so it dips to the same sliver and the sliver says it is a
        // single. It still carries no caret, no pointing cursor and
        // no track fetch, because there is nothing to open.
        readonly property bool peekable: expandable || single
        readonly property bool peeking: peekable && !qexp && cardHover.containsMouse
        // How many track rows the ledger holds, and how many of
        // them are actually built. A ledger row is not cheap (four
        // texts, two DecryptText cells, three running Behaviors),
        // and the Repeater below is not virtualised, so the count
        // is the cost. An album is 10 to 30 rows, which is what
        // this was written for; a playlist is routinely hundreds
        // and can be thousands, and the peek is reached by the
        // pointer merely crossing the row, so an unbounded count
        // would spend a quarter of a second of the GUI thread on a
        // gesture nobody made on purpose. The peek builds only
        // what its 30px sliver can show; the expansion, which the
        // user did ask for, builds up to host.queueLedgerMax and
        // says how many rows it is not showing.
        readonly property int ledgerLen: (host.queueTracks[model.qid] || []).length
        // While the sliver is still CLOSING it keeps what it was
        // showing. Bound to the hover alone, the ledger emptied on
        // the frame the pointer left and the card then spent the
        // whole 220ms retract closing on an empty box: the motion
        // read as the row swallowing its own content rather than
        // as a peek folding away. Only the closing half is held
        // (the opening one has nothing yet to keep), and a single's
        // sliver, whose whole content is one line of text, was the
        // clearest case of all.
        readonly property bool ledgerHolding: qexp || peeking || qtrackAnim.running
        readonly property int ledgerShown: qexp ? Math.min(ledgerLen, host.queueLedgerMax) : ledgerHolding ? Math.min(ledgerLen, host.queueLedgerPeek) : 0
        function qtoggle() {
          // A single has no ledger to open; the card is the whole story.
          if (!expandable) {
            return
          }
          var e = Object.assign({}, host.queueExpanded)
          if (e[model.qid]) {
            delete e[model.qid]
          } else {
            e[model.qid] = true
            waves.loadQueueTracks(model.qid)
          }
          host.queueExpanded = e
        }
        // Driven by the host lingerClock via the model, so the
        // fold works with the drawer closed (no delegate) too.
        readonly property bool leaving: model.leaving === true
        // What this release is being fetched at. Once its tracks
        // report, they are the truth: an album whose tracks did not
        // all land at the same tier says MIXED and the expanded
        // ledger itemizes it.
        //
        // Both of these come off the ROW, rolled up by the bridge
        // from the registry it keeps for every job. Computing them
        // here from host.queueTracks[qid] would depend on
        // loadQueueTracks, a network fetch that only runs when the
        // user expands the row: a row nobody opened would go on
        // advertising the tier it had ASKED for and could never
        // say MIXED, which is precisely the row that needed to,
        // since nobody was looking at its ledger.
        readonly property var tierMix: JSON.parse(model.mixJson || "[]")
        // The one tier they all landed at. It outranks the asked-for
        // tier the moment the first track reports: a release with no
        // hi-res master answers a HI-RES request in LOSSLESS from
        // end to end, and no MIXED will ever catch that (one tier is
        // not a mix).
        readonly property string landed: "" + (model.landed || "")
        // Before anything lands: the request floored by the
        // release's advertised ceiling, so a lossless-only album
        // asked for in HI-RES never promises HI-RES.
        readonly property string tier: tierMix.length > 1 ? "" : landed !== "" ? landed : host.tierFloor(model.quality, model.expected)
        width: ListView.view.width
        property real bodyH: actCol.implicitHeight + 18
        height: (collapsed || leaving) ? 0 : bodyH + 8
        opacity: leaving ? 0 : 1
        clip: true
        // While the peek/expand animation drives the inner list height,
        // this outer Behavior must idle, otherwise it re-targets every
        // frame, chasing the moving bodyH, and the motion turns mushy.
        Behavior on height {
          enabled: !qtrackAnim.running
          NumberAnimation {
            duration: 280
            easing.type: Easing.OutCubic
          }
        }
        Behavior on opacity {
          NumberAnimation {
            duration: 240
          }
        }

        // Finish flow: ✓ DONE chip pops, then the row collapses +
        // fades in place and is moved into Completed. The timing
        // (doneAt + 5s) lives on the model row and is driven by
        // the host lingerClock, not here: a delegate only exists
        // while the drawer shows it, so per-row timers meant a
        // closed drawer never folded anything.
        onStChanged: if (qrow.lingering)
          chipPop.restart()

        // queue card (Completed rows use the same card as
        // Downloading/Queued, art thumb, caret, hover peek and
        // expand included, just in the quieter completed palette) ----
        Rectangle {
          id: activeRect
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          height: actCol.implicitHeight + 18
          radius: 8
          color: qrow.isComp ? surface : surface2
          border.color: qrow.isComp ? (cardHover.containsMouse && qrow.peekable ? outline : line1) : qrow.st === "done" ? greenDim : cardHover.containsMouse ? outline : border1
          clip: true
          Behavior on border.color {
            ColorAnimation {
              duration: 120
            }
          }
          // Card-wide expand toggle for album rows, and the row's keyboard
          // home. A MouseArea rather than a TapAction, deliberately: the
          // row's pointer and keyboard actions differ (the click only opens
          // a ledger; Return also retries a settled row that has none), and
          // TapAction's one `triggered` handler exists to make those paths
          // agree. This is DownloadButton's shape: one MouseArea carrying
          // the accessible contract, its pointer and its keys free to take
          // different branches. Declared first so the retry/cancel tap areas
          // (later siblings) stay on top.
          MouseArea {
            id: cardHover
            objectName: "queueRowCard"
            anchors.fill: parent
            // Enabled for every row so Tab can reach it: a settled row is
            // still removable and a live one cancellable. Hover stays where
            // it was, so no row grows a highlight its click does not back
            // up; the hand still only appears where a click expands.
            hoverEnabled: qrow.peekable
            cursorShape: qrow.expandable ? Qt.PointingHandCursor : Qt.ArrowCursor
            activeFocusOnTab: qrow.rowFocusable
            Accessible.role: Accessible.Button
            Accessible.name: qrow.spokenName()
            Accessible.onPressAction: qrow.rowActivate()
            Keys.onReturnPressed: function (event) {
              if (!event.isAutoRepeat) {
                event.accepted = true
                qrow.rowActivate()
              }
            }
            Keys.onEnterPressed: function (event) {
              if (!event.isAutoRepeat) {
                event.accepted = true
                qrow.rowActivate()
              }
            }
            Keys.onSpacePressed: function (event) {
              if (!event.isAutoRepeat) {
                event.accepted = true
                qrow.rowActivate()
              }
            }
            onClicked: qrow.qtoggle()
            // Fetch the track list as soon as the peek starts so the
            // sliver shows real titles, not just "Loading tracks…".
            onContainsMouseChanged: {
              if (containsMouse && qrow.expandable && !qrow.qexp && !(host.queueTracks[model.qid]))
                waves.loadQueueTracks(model.qid)
            }
            // The focus ring TapAction draws for its hosts: an overlay, so
            // the card's own fill/border recipe is never repainted.
            Rectangle {
              anchors.fill: parent
              radius: 8
              color: "transparent"
              border.width: 2
              border.color: accent
              visible: cardHover.activeFocus
            }
          }
          ColumnLayout {
            id: actCol
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 12
            anchors.rightMargin: 10
            anchors.topMargin: 9
            spacing: 6
            RowLayout {
              Layout.fillWidth: true
              spacing: 11
              // Cover thumb with the status dot riding its corner;
              // falls back to the bare dot when there's no art.
              Item {
                id: qthumb
                readonly property bool hasArt: (model.art || "") !== ""
                Layout.alignment: Qt.AlignVCenter
                implicitWidth: hasArt ? 34 : 8
                implicitHeight: hasArt ? 34 : 8
                Art {
                  host: queueDrawer.host
                  anchors.fill: parent
                  url: model.art || ""
                  visible: qthumb.hasArt
                }
                Rectangle {
                  width: qthumb.hasArt ? 11 : 8
                  height: width
                  radius: width / 2
                  color: host.statusColor(qrow.st)
                  border.color: surface2
                  border.width: qthumb.hasArt ? 2 : 0
                  anchors.right: parent.right
                  anchors.bottom: parent.bottom
                  anchors.rightMargin: qthumb.hasArt ? -3 : 0
                  anchors.bottomMargin: qthumb.hasArt ? -3 : 0
                }
              }
              Text {
                visible: qrow.expandable
                text: "›"
                rotation: qrow.qexp ? 90 : 0
                color: (qrow.qexp || cardHover.containsMouse) ? accent : textDim
                font.pixelSize: 13
                Layout.alignment: Qt.AlignVCenter
                Layout.leftMargin: -5
                Layout.rightMargin: -4
                Behavior on rotation {
                  NumberAnimation {
                    duration: 160
                    easing.type: Easing.OutCubic
                  }
                }
                Behavior on color {
                  ColorAnimation {
                    duration: 120
                  }
                }
              }
              ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                spacing: 1
                Text {
                  textFormat: Text.PlainText
                  text: model.name
                  color: textHi
                  font.pixelSize: 13
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                }
                Text {
                  textFormat: Text.PlainText  // composed from a remote artist name
                  text: {
                    var a = model.artist ? model.artist + " · " : ""
                    // Session supervision: HELD and THROTTLED
                    // are presentations, not new states. A
                    // held row stays queued with its reason;
                    // a throttled row stays running with its
                    // countdown.
                    if (qrow.st === "queued")
                      return a + (model.reason ? model.reason : "Queued")
                    // A failure states WHAT failed when the job
                    // knows ("6 of 501 tracks failed"): on a long
                    // playlist the collapsed row is the whole
                    // diagnosis, and the bare word could not tell
                    // a run that saved 495 songs from one that
                    // saved none.
                    if (qrow.st === "failed")
                      return a + (model.reason ? model.reason : "Failed")
                    if (qrow.st === "cancelled")
                      return a + (model.reason ? model.reason : "Stopped")
                    // A throttled row states its countdown inside
                    // its normal downloading state.
                    if (qrow.st === "running" && model.reason)
                      return a + model.reason
                    if (model.collection && model.tracks > 0)
                      // Floor, not round: the roll-up now moves with the in-flight
                      // track, and 6.4 done of 12 must read "6/12", not "7/12".
                      // The epsilon absorbs float error at exact completions.
                      return a + (qrow.st === "done" ? model.tracks : Math.floor(model.progress / 100 * model.tracks + 1e-6)) + "/" + model.tracks + " tracks"
                    if (qrow.st === "running")
                      return a + Math.round(model.progress) + "%"
                    return a + (qrow.st === "done" ? "Done" : qrow.st)
                  }
                  color: textLo
                  font.family: mono
                  font.pixelSize: 11
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                }
                // Integrity quarantine: the bad bytes live
                // in the quarantine folder with no other
                // way in, so the failed row carries the
                // two actions. OPEN reveals the folder;
                // DELETE removes the copies (the skip-list
                // mark stays until a verified REDOWNLOAD).
                RowLayout {
                  visible: qrow.st === "failed" && Number(model.quarantineCount || 0) > 0
                  spacing: 6
                  Layout.topMargin: 2
                  SpecBtn {
                    compact: true
                    label: "OPEN QUARANTINE"
                    onClicked: waves.openQuarantine(model.qid)
                  }
                  SpecBtn {
                    compact: true
                    danger: true
                    label: "DELETE COPY"
                    onClicked: waves.deleteQuarantine(model.qid)
                  }
                }
              }
              Rectangle {
                id: doneChip
                // Chip pops while the row lingers; in the Completed
                // group the status dot on the art carries "done".
                Layout.alignment: Qt.AlignVCenter
                visible: qrow.st === "done" && !qrow.isComp
                radius: 8
                color: greenCont
                border.color: greenDim
                implicitHeight: 24
                implicitWidth: chipRow.implicitWidth + 18
                Row {
                  id: chipRow
                  anchors.centerIn: parent
                  spacing: 6
                  Ico {
                    name: "check"
                    color: accent
                    size: 13
                    anchors.verticalCenter: parent.verticalCenter
                  }
                  Text {
                    text: "DONE"
                    color: accent
                    font.family: mono
                    font.pixelSize: 11
                    font.bold: true
                    font.letterSpacing: 0.8
                    anchors.verticalCenter: parent.verticalCenter
                  }
                }
                SequentialAnimation {
                  id: chipPop
                  PropertyAction {
                    target: doneChip
                    property: "scale"
                    value: 0.5
                  }
                  NumberAnimation {
                    target: doneChip
                    property: "scale"
                    to: 1.12
                    duration: 170
                    easing.type: Easing.OutCubic
                  }
                  NumberAnimation {
                    target: doneChip
                    property: "scale"
                    to: 1.0
                    duration: 130
                    easing.type: Easing.OutCubic
                  }
                }
              }
              // The quality the row is fetching at, beside the
              // dismiss X and centred with it. Compact: the
              // drawer has room for the tier word, not for the
              // full spec behind it, and the expanded ledger
              // states the per-track detail anyway. The DONE
              // chip owns the spare width while it lingers.
              QualTag {
                host: queueDrawer.host
                Layout.alignment: Qt.AlignVCenter
                visible: !doneChip.visible && (qrow.tier !== "" || qrow.tierMix.length > 1)
                compact: true
                q: qrow.tier
                mix: qrow.tierMix
              }
              RetryMark {
                objectName: "queueRetryMark"
                Layout.alignment: Qt.AlignVCenter
                visible: host.retryableStatus(qrow.st)
                color: accent
                box: 16
                TapAction {
                  objectName: "queueRowRetry"
                  anchors.fill: parent
                  anchors.margins: -4
                  accessibleLabel: "Retry " + qrow.spokenName()
                  focusRadius: 4
                  // A row on its way out (collapsed Completed or leaving)
                  // must not keep a stop on its invisible controls.
                  activeFocusOnTab: qrow.rowFocusable
                  onTriggered: waves.retryQueueItem(model.qid)
                }
              }
              Ico {
                Layout.alignment: Qt.AlignVCenter
                readonly property bool active: qrow.live
                name: "close"
                size: 14
                bold: active ? 8 : 0   // heavier while cancellable
                color: cancMa.containsMouse ? red : (active ? textLo : textDim)
                TapAction {
                  id: cancMa
                  objectName: "queueRowGiveUp"
                  anchors.fill: parent
                  accessibleLabel: (qrow.live ? "Cancel " : "Remove ") + qrow.spokenName()
                  focusRadius: 3
                  // Same gate as the card: a collapsed or leaving row's ✕
                  // is not on screen and must not be a tab stop.
                  activeFocusOnTab: qrow.rowFocusable
                  onTriggered: qrow.giveUp()
                }
              }
            }
            Item {
              id: qbarSlot
              Layout.fillWidth: true
              // The slot is the bar's own height: four rows of
              // 3px cells with 1px gaps (15px), the same dense
              // grid as the download button's running face.
              Layout.preferredHeight: qrow.st === "running" ? 15 : 0
              opacity: qrow.st === "running" ? 1 : 0
              clip: true
              Behavior on Layout.preferredHeight {
                NumberAnimation {
                  duration: 300
                  easing.type: Easing.OutCubic
                }
              }
              Behavior on opacity {
                NumberAnimation {
                  duration: 240
                }
              }
              Loader {
                // Collapsing the slot to height 0 and opacity
                // 0 hides this grid, it does not spare it: an
                // invisible subtree is still BUILT, the same
                // reason the download button's smaller matrix
                // sits behind a Loader. This one spans the
                // whole drawer, so every QUEUED row was
                // paying for 364 cells at the 420px floor and
                // past a thousand with the drawer dragged
                // wide, and a flick through a long queue
                // dropped frames on rows that show nothing.
                // Held active through the fade so the end of
                // a run does not unload a lit grid in one
                // frame.
                active: qrow.st === "running" || qbarSlot.opacity > 0
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 15
                sourceComponent: DotMatrix {
                  objectName: "queueRowMatrix"
                  ledPulse: host.ledPulse
                  shimmerPhase: host.shimmerPhase
                  queueEdgeHeld: host.queueEdgeHeld
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.top: parent.top
                  rows: 4
                  dot: 3
                  gap: 1
                  maxCols: 0
                  // The ends fade on the shelf edge fades'
                  // curve like the download face's (28px, a
                  // shade shorter than a shelf's 34), and
                  // the outer rows' cells shade into the card
                  // from their outer edge, since this bar has
                  // no outline to end at.
                  edgeFadeW: 28
                  edgeSoft: 0.15
                  pulse: qrow.st === "running"
                  pct: qrow.st === "done" ? 100 : model.progress
                  // 100% but still running = the final steps (merge,
                  // decrypt, tag) are in flight: twinkle, don't freeze.
                  finishing: qrow.st === "running" && model.progress >= 99.9
                  onColor: qrow.st === "failed" ? red : qrow.st === "queued" ? cyanDim : accent
                }
              }
            }
            // expanded per-track list (album order, live state)
            // Hovering a collapsed album card "peeks" the top of this
            // list, the card bottom bounces down just far enough to
            // show the track view exists, and retracts on hover-out.
            Item {
              id: qtrackClip
              // Named so a scenario can watch the sliver
              // retract and prove it is not empty on the
              // way (see ledgerHolding above).
              objectName: "qLedgerClip"
              readonly property bool shown: qrow.qexp || qrow.peeking
              visible: shown || implicitHeight > 0.5
              clip: true
              // Off the ANIMATED height, not off `shown`: bound to
              // the flag it added its 2px the instant the pointer
              // arrived, a step the card took before the smooth part
              // of the motion had begun.
              Layout.fillWidth: true
              Layout.bottomMargin: implicitHeight > 0.5 ? 2 : 0
              implicitHeight: qrow.qexp ? qtrackCol.implicitHeight : (qrow.peeking ? 30 : 0)
              Behavior on implicitHeight {
                NumberAnimation {
                  id: qtrackAnim
                  // OutCubic, NOT OutBack. A spring overshoots its
                  // target and comes back, which on a peek driven by
                  // the POINTER reads as the card opening and then
                  // retracting by itself while the pointer sits
                  // still, and on hover-out it aims the height below
                  // zero before returning to it. Sweeping down a
                  // list of rows played that wobble once per row.
                  // A hover response has to settle where it stops.
                  duration: 220
                  easing.type: Easing.OutCubic
                }
              }
              ColumnLayout {
                id: qtrackCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                spacing: 3
                Rectangle {
                  Layout.fillWidth: true
                  implicitHeight: 1
                  color: line1
                }
                Text {
                  textFormat: Text.PlainText
                  visible: qrow.ledgerHolding && !qrow.single && (host.queueTracks[qrow.model.qid] || []).length === 0
                  text: "Loading tracks…"
                  color: textDim
                  font.family: mono
                  font.pixelSize: 10
                }
                // What the single's peek is for: the sliver
                // answers the hover instead of waiting on a
                // track list that would only repeat the card.
                Text {
                  objectName: "qSingleNote"
                  textFormat: Text.PlainText
                  visible: qrow.ledgerHolding && qrow.single
                  text: "Single track, nothing to expand"
                  color: textDim
                  font.family: mono
                  font.pixelSize: 10
                }
                Repeater {
                  // The count, not the array: every live tick
                  // (queueTrackState/Pct, 2 a second while an album
                  // downloads) signals a change on host.queueTracks,
                  // and an array model tears down and rebuilds every
                  // row per tick. Each rebuild costs a layout-settle
                  // frame, which reads as the open sliver vibrating
                  // under the pointer. With the count as the model
                  // the rows stay alive and each one's texts
                  // re-evaluate in place.
                  model: qrow.ledgerShown
                  delegate: RowLayout {
                    required property int index
                    // Depends on host.queueTracks, so each tick
                    // refreshes this row's snapshot in place.
                    readonly property var td: (host.queueTracks[qrow.model.qid] || [])[index] || ({})
                    Layout.fillWidth: true
                    spacing: 8
                    Text {
                      textFormat: Text.PlainText
                      text: (td.num || "") + ""
                      color: textDim
                      font.family: mono
                      font.pixelSize: 10
                      Layout.preferredWidth: 16
                      horizontalAlignment: Text.AlignRight
                    }
                    Text {
                      objectName: "qTrackTitle"
                      textFormat: Text.PlainText
                      text: td.title || ""
                      // Grey until the track is actually
                      // yours: a finished download or a
                      // copy already in the library reads
                      // bright, a failure reads red, the
                      // rest stay quiet.
                      color: td.status === "failed" ? red : (td.status === "done" || td.status === "skipped" || td.status === "owned") ? textHi : textLo
                      Behavior on color {
                        ColorAnimation {
                          duration: 260
                        }
                      }
                      font.pixelSize: 11
                      elide: Text.ElideRight
                      Layout.fillWidth: true
                    }
                    // The tier, in a column of its own so
                    // qualities stack and scan vertically.
                    // Faded while it is still only what the
                    // job is asking for, full strength once
                    // the file has landed at it.
                    Text {
                      objectName: "qTrackTier"
                      textFormat: Text.PlainText
                      readonly property string delivered: "" + (td.quality || "")
                      readonly property string tier: host.queueTrackTier(delivered, "" + (td.status || ""), "" + (qrow.model.quality || ""), "" + (td.expected || ""))
                      // Still only the request: there is a tier to
                      // state and no file has landed at it yet.
                      readonly property bool promised: delivered === "" && tier !== ""
                      visible: tier !== ""
                      text: tier
                      color: host.qualFg(tier)
                      opacity: promised ? 0.45 : 1
                      Behavior on opacity {
                        NumberAnimation {
                          duration: 260
                        }
                      }
                      font.family: mono
                      font.pixelSize: 10
                      Layout.preferredWidth: 56
                      horizontalAlignment: Text.AlignRight
                    }
                    // The outcome in words: a track you
                    // already hold says so, rather than
                    // spending the reader a glyph they have
                    // to learn. "pending" is the state a
                    // fetched track list starts in (see
                    // queueTrackTier), so it reads QUEUED
                    // like the tracks awaiting their turn,
                    // never a blank dot. One overlapped
                    // cell so a state switch crossfades:
                    // a downloading track is the word
                    // DOWNLOADING, faded, with the full
                    // green pouring over it in lockstep
                    // with the track's own progress.
                    Item {
                      id: scell
                      readonly property bool dl: td.status === "running"
                      // The stream finishing is not the work
                      // finishing: extraction, tagging and the
                      // move still run with the bar at 100.
                      // Same threshold as the LED twinkle.
                      readonly property bool fin: dl && (td.pct || 0) >= 99.9
                      onDlChanged: if (dl && dlWord._live)
                        dlWord.replay()
                      onFinChanged: if (fin && finWord._live)
                        finWord.replay()
                      Layout.preferredWidth: 78
                      implicitHeight: Math.max(sWord.implicitHeight, dlWord.implicitHeight)
                      DecryptText {
                        id: sWord
                        objectName: "qTrackWord"
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        // Hidden while the DOWNLOADING word
                        // owns the cell; at half strength
                        // while IN LIBRARY is still only
                        // predicted ("owned"), the same
                        // half strength every other
                        // prediction in this drawer wears,
                        // and it fills in when the run
                        // reaches the track and agrees.
                        opacity: scell.dl ? 0 : (td.status === "owned" ? 0.5 : 1)
                        visible: opacity > 0
                        Behavior on opacity {
                          NumberAnimation {
                            duration: 180
                          }
                        }
                        // UNAVAILABLE is TIDAL's answer,
                        // not a failure of ours: it wears
                        // the muted red so it reads as
                        // "you did not get this one"
                        // without the alarm of RETRY,
                        // which would promise something a
                        // retry cannot deliver.
                        target: td.status === "done" ? "COMPLETED" : td.status === "failed" ? "FAILED" : td.status === "unavailable" ? "UNAVAILABLE" : (td.status === "skipped" || td.status === "owned") ? "IN LIBRARY" : td.status === "cancelled" ? "STOPPED" : (td.status === "queued" || td.status === "pending") ? "QUEUED" : td.status === "running" ? "" : "·"
                        // IN LIBRARY speaks in the download
                        // button's two voices: green when
                        // Waves wrote that exact file (the
                        // ownership ledger, a fact), gold
                        // when the library scan matched it
                        // by tags (a guess). Its tier cell
                        // keeps the copy's own quality.
                        color: td.status === "done" ? accent : td.status === "failed" ? red : td.status === "unavailable" ? redDim : (td.status === "skipped" || td.status === "owned") ? (td.owned === "claim" ? libAccent : accent) : textDim
                        Behavior on color {
                          ColorAnimation {
                            duration: 260
                          }
                        }
                        font.pixelSize: 10
                        font.bold: target !== "·" && target !== "QUEUED" && target !== "STOPPED"
                      }
                      Item {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: dlWord.implicitWidth
                        height: dlWord.implicitHeight
                        opacity: scell.dl && !scell.fin ? 1 : 0
                        visible: opacity > 0
                        Behavior on opacity {
                          NumberAnimation {
                            duration: 260
                          }
                        }
                        DecryptText {
                          id: dlWord
                          // Faded green, warming as the
                          // download progresses, while the
                          // full-bright fill sweeps over it.
                          // Decrypts in each time the track
                          // starts downloading.
                          target: "DOWNLOADING"
                          color: Qt.alpha(accent, 0.28 + 0.4 * Math.max(0, Math.min(100, td.pct || 0)) / 100)
                          font.pixelSize: 10
                          font.bold: true
                        }
                        // The green ink pours over the faded
                        // word in lockstep with the track's
                        // own progress, smoothed between ticks.
                        Item {
                          clip: true
                          anchors.left: parent.left
                          anchors.top: parent.top
                          anchors.bottom: parent.bottom
                          width: parent.width * Math.max(0, Math.min(100, td.pct || 0)) / 100
                          Behavior on width {
                            NumberAnimation {
                              duration: 200
                              easing.type: Easing.OutCubic
                            }
                          }
                          Text {
                            textFormat: Text.PlainText
                            // Mirrors the scramble frames
                            // so the fill stays letter-
                            // aligned while it decodes.
                            text: dlWord.text
                            color: accent
                            font.family: mono
                            font.pixelSize: 10
                            font.bold: true
                          }
                        }
                      }
                      // The stream landing hands the slot to
                      // FINISHING: its own word with its OWN
                      // fill riding fpct (the finalize steps:
                      // extract, tag, move), so it opens
                      // empty and earns its ink, instead of
                      // inheriting the finished download's
                      // full fill and draining backwards.
                      Item {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: finWord.implicitWidth
                        height: finWord.implicitHeight
                        opacity: scell.fin ? 1 : 0
                        visible: opacity > 0
                        Behavior on opacity {
                          NumberAnimation {
                            duration: 260
                          }
                        }
                        DecryptText {
                          id: finWord
                          target: "FINISHING"
                          color: Qt.alpha(accent, 0.28 + 0.4 * Math.max(0, Math.min(100, td.fpct || 0)) / 100)
                          font.pixelSize: 10
                          font.bold: true
                        }
                        Item {
                          clip: true
                          anchors.left: parent.left
                          anchors.top: parent.top
                          anchors.bottom: parent.bottom
                          width: parent.width * Math.max(0, Math.min(100, td.fpct || 0)) / 100
                          Behavior on width {
                            NumberAnimation {
                              duration: 200
                              easing.type: Easing.OutCubic
                            }
                          }
                          Text {
                            textFormat: Text.PlainText
                            text: finWord.text
                            color: accent
                            font.family: mono
                            font.pixelSize: 10
                            font.bold: true
                          }
                        }
                      }
                    }
                  }
                }
                // The ledger is capped, so say what it is not
                // showing rather than ending on a row that
                // looks like the last one. Only ever seen on a
                // playlist far larger than the drawer can list.
                Text {
                  objectName: "qTrackMore"
                  textFormat: Text.PlainText
                  readonly property int rest: qrow.ledgerLen - qrow.ledgerShown
                  visible: qrow.qexp && rest > 0
                  text: rest + (rest === 1 ? " more track" : " more tracks")
                  color: textDim
                  font.family: mono
                  font.pixelSize: 10
                  Layout.topMargin: 2
                }
              }
            }
          }
          // 5-second countdown bar, drains while the ✓ DONE chip
          // lingers. Sized from doneAt so a delegate created
          // mid-linger (drawer opened late) starts at the true
          // remaining fraction, not a fresh full bar.
          Rectangle {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            height: 2
            radius: 1
            color: accent
            opacity: 0.6
            visible: qrow.lingering && !qrow.leaving
            NumberAnimation on width {
              running: qrow.lingering && !qrow.leaving
              from: activeRect.width * Math.max(0, 1 - (Date.now() - model.doneAt) / 5000)
              to: 0
              duration: Math.max(1, 5000 - (Date.now() - model.doneAt))
              easing.type: Easing.Linear
            }
          }
        }
      }
    }
    RowLayout {
      Layout.fillWidth: true
      spacing: 8
      // One button, not two: the per-section CLEARs above handle the
      // targeted cases, so all this one owes the user is "empty the
      // list". It never touches a transfer already writing bytes,
      // which the row's own stop control is for.
      // Pushes the button to the trailing edge, under the section
      // headers' own controls, so the three CLEARs line up vertically.
      Item {
        Layout.fillWidth: true
      }
      // The exit prompt's own danger button, hugging its label: full
      // width is for modal CTAs, an inline button that stretches is
      // just a wide empty box.
      SpecBtn {
        danger: true
        label: "CLEAR ALL"
        onClicked: waves.clearQueue()
      }
    }
  }

  // Drag the drawer wider by its own edge
  // The handle IS the border, never a bar beside it. `parent` here is the
  // Popup's own content item, which sits at leftPadding (the background's
  // 1px border), so undoing exactly that puts x=0 on the border line.
  // Declared after the ColumnLayout, which is what puts it on top; it
  // covers the layout's 16px left margin, where nothing else lives.
  Item {
    id: queueGrip
    anchors.left: parent.left
    anchors.leftMargin: -queueDrawer.leftPadding
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    width: 16
    z: 50

    // Where the grip point is on the edge (the spot the magnet glow
    // centres on). WRITTEN by the MouseArea below, never read off
    // mouseY: it must not follow the pointer during the drag (the
    // glow's squeeze stays on the spot that was taken hold of), and
    // letting go must leave it exactly where it was let go. Bound to
    // mouseY it did the opposite, snapping on release to wherever the
    // pointer had wandered to by then, or to a stale reading if the
    // pointer had left the 16px band altogether.
    property real handY: 0
    readonly property bool lit: gripMouse.containsMouse || gripMouse.pressed

    // True only while the grip point is being PLACED rather than
    // moved: the pointer arriving on the band, or taking hold of it.
    // Both are jumps to somewhere the light was not, and the light
    // belongs under the pointer at once; the smoothing below is for
    // travelling along the edge. Without this, grabbing the edge low
    // down after the light was last seen high up drags a comet
    // through the drag's first quarter second.
    property bool placing: false
    function placeHand(y) {
      placing = true
      handY = y
      placing = false
    }

    Rectangle {
      x: 0
      width: 1
      height: parent.height
      color: line1
    }

    // The edge lights where the pointer is before anything is grabbed, and
    // runs the full height once it is: the whole edge is the handle,
    // not one notch on it.
    Rectangle {
      id: gripGlow
      x: 0
      width: gripMouse.pressed ? 4 : 3
      // What the light is centred on: the grip point, held clear of the
      // very ends so a blob in a corner is not half off the edge.
      // The travel animation lives HERE rather than on y, because y
      // moves when the HEIGHT changes too, and the two would disagree:
      // y smoothed by distance (1600 px/s) while the height is timed
      // (220ms), so letting go near the bottom of a tall window would
      // re-form the finished blob up at the top and then slide it down.
      // Centre and height cannot disagree.
      property real centre: Math.max(35, Math.min(parent.height - 35, queueGrip.handY))
      Behavior on centre {
        enabled: !queueGrip.placing
        SmoothedAnimation {
          velocity: 1600
        }
      }
      // Grabbed, the light runs the whole edge: twice the drawer's
      // height, so its own fade stays off screen and only the bright
      // middle shows. Let go, it collapses back to a blob. Nothing
      // but the height changes between those two, and it changes
      // about the centre, so both ends travel the same distance in
      // the same time and the grip point keeps the middle throughout.
      height: gripMouse.pressed ? parent.height * 2 : 190
      y: centre - height / 2
      opacity: queueGrip.lit ? 1 : 0
      gradient: Gradient {
        GradientStop {
          position: 0.0
          color: Qt.rgba(accent.r, accent.g, accent.b, 0)
        }
        GradientStop {
          position: 0.42
          color: Qt.rgba(accent.r, accent.g, accent.b, 0.93)
        }
        GradientStop {
          position: 0.58
          color: Qt.rgba(accent.r, accent.g, accent.b, 0.93)
        }
        GradientStop {
          position: 1.0
          color: Qt.rgba(accent.r, accent.g, accent.b, 0)
        }
      }
      Behavior on height {
        NumberAnimation {
          duration: 220
          easing.type: Easing.OutCubic
        }
      }
      Behavior on width {
        NumberAnimation {
          duration: 140
        }
      }
      Behavior on opacity {
        NumberAnimation {
          duration: 180
        }
      }
    }
    // The stretch being squeezed, brighter than the lit edge around it
    // so the grip still reads once the glow has gone full height.
    Rectangle {
      x: 0
      width: 4
      height: gripMouse.pressed ? 56 : 0
      y: queueGrip.handY - height / 2
      color: accentSoft
      Behavior on height {
        NumberAnimation {
          duration: 130
          easing.type: Easing.OutCubic
        }
      }
    }

    MouseArea {
      id: gripMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.SplitHCursor
      // A horizontal drag is also the Drawer's own dismiss gesture,
      // which is the same axis this one drags in. Without it the
      // drawer slides shut instead of resizing.
      preventStealing: true
      onPressedChanged: host.queueEdgeHeld = pressed
      property real startScene: 0
      property real startWidth: 0
      // Hovering, the glow follows the pointer; holding, its centre
      // stays put and the pointer's job is the width instead. The
      // pressed guard matters: mid-drag the edge lags the pointer,
      // and a vertical wiggle makes the pointer leave and re-enter
      // the band, each re-entry an onEntered. Unguarded, every one
      // of them would teleport the glow to the pointer's y, which
      // reads as jumping up and down while resizing.
      onEntered: if (!pressed)
        queueGrip.placeHand(mouseY)
      onPressed: function (m) {
        queueGrip.placeHand(m.y)
        startScene = mapToItem(null, m.x, m.y).x
        startWidth = queueDrawer.width
      }
      onPositionChanged: function (m) {
        if (!pressed) {
          queueGrip.handY = m.y
          return
        }
        var want = startWidth + (startScene - mapToItem(null, m.x, m.y).x)
        host.queueWidth = Math.max(420, Math.min(host.width - 80, want))
      }
    }
  }
}

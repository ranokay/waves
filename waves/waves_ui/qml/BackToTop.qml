import QtQuick

// Scroll-edge dressing plus the "back to top" badge, one window-level
// instance serving whichever view is on screen. Three pieces:
//   1. LIP edge fades: a short dense darkening at the top and bottom of
//      the scroll viewport so rows fade in and out of frame instead of
//      being cut off hard at the chrome edge.
//   2. Rolodex roll: rows whose center enters the edge band tilt subtly
//      around their horizontal axis (real perspective), so the list reads
//      like a conveyor curling over a drum edge.
//   3. The INLINE crest pill: appears once the page has been scrolled
//      about a viewport down, riding the top edge; one click glides back.
// Split out of Main.qml (#315). The palette values are local copies of
// Main.qml's static literals — the SettingsPage.qml convention; keep them in
// step if the palette changes.
Item {
    id: btt
    property var flick: null
    readonly property color accent: "#3dff6e"
    readonly property color accentDim: "#22a64a"
    readonly property color textHi: "#e6e8ec"
    readonly property real btnTrack: 0
    readonly property string mono: monoFont
    anchors.fill: parent
    readonly property bool on: flick !== null && flick.visible && flick.contentY > flick.height * 0.75
    NumberAnimation {
        id: bttAnim
        property: "contentY"
        to: 0
        duration: 450
        easing.type: Easing.OutCubic
    }
    // Viewport geometry in window coordinates. The leading terms in the
    // sequence expressions are binding dependencies: mapToItem alone is
    // not notifiable, so re-evaluate when the window or view resizes.
    readonly property bool live: flick !== null && flick.visible
    readonly property real fTop: live ? (btt.height, flick.height, flick.mapToItem(btt, 0, 0).y) : 0
    readonly property real fX: live ? (btt.width, flick.width, flick.mapToItem(btt, 0, 0).x) : 0
    readonly property real fW: live ? flick.width : 0
    readonly property real fBottom: live ? fTop + flick.height : 0

    // LIP edge fades
    // Scroll-gated: a fade exists to soften rows being cut off by the
    // viewport edge, so when nothing is cut off there must be no fade.
    // At the very top of a page (contentY 0) the top fade is fully
    // transparent, so heroes, artist art and the back bar are never
    // dimmed for no reason; it ramps in over the first fadeH pixels of
    // scroll. Mirrored at the bottom: the fade lifts as the end of the
    // page arrives, and a page too short to scroll shows no fades at all.
    readonly property real fadeH: 34
    Rectangle {
        x: btt.fX
        y: btt.fTop
        width: btt.fW
        height: btt.fadeH
        visible: btt.live && opacity > 0
        opacity: btt.live ? Math.min(1, Math.max(0, btt.flick.contentY) / btt.fadeH) : 0
        gradient: Gradient {
            GradientStop {
                position: 0
                color: "#0d0f12"
            }
            GradientStop {
                position: 0.25
                color: Qt.alpha("#0d0f12", 0.82)
            }
            GradientStop {
                position: 0.6
                color: Qt.alpha("#0d0f12", 0.28)
            }
            GradientStop {
                position: 1
                color: Qt.alpha("#0d0f12", 0)
            }
        }
    }
    Rectangle {
        x: btt.fX
        y: btt.fBottom - btt.fadeH
        width: btt.fW
        height: btt.fadeH
        visible: btt.live && opacity > 0
        opacity: btt.live ? Math.min(1, Math.max(0, btt.flick.contentHeight - btt.flick.height - btt.flick.contentY) / btt.fadeH) : 0
        rotation: 180
        gradient: Gradient {
            GradientStop {
                position: 0
                color: "#0d0f12"
            }
            GradientStop {
                position: 0.25
                color: Qt.alpha("#0d0f12", 0.82)
            }
            GradientStop {
                position: 0.6
                color: Qt.alpha("#0d0f12", 0.28)
            }
            GradientStop {
                position: 1
                color: Qt.alpha("#0d0f12", 0)
            }
        }
    }

    // rolodex roll
    // Each row gets a Rotation bound to its own view (captured at creation,
    // so rows on backgrounded pages keep working when the user returns).
    readonly property real rollMax: 9
    readonly property real rollBand: 56
    // The tilt angle below reads row.mapToItem(fl), which is NOT reactive, so
    // the binding only re-evaluates on its one live dependency: fl.contentY
    // (a scroll). A tab switch or a filter change repositions rows without
    // moving contentY, which would leave every angle frozen at its old value
    // until the next scroll. Bumping rollTick on those events (see armRoll and
    // onFlickChanged) is the dependency that forces a recompute on demand.
    property int rollTick: 0
    Component {
        id: bttRollComp
        Rotation {
            property Item row
            property Item fl
            origin.x: row ? row.width / 2 : 0
            origin.y: row ? row.height / 2 : 0
            axis {
                x: 1
                y: 0
                z: 0
            }
            angle: {
                var _t = btt.rollTick
                // re-eval on tab switch / filter / reflow, not only scroll
                if (!row || !fl)
                    return 0
                // Only row-sized items may tilt. Anything taller (a shelf
                // section, an expanded album panel) projects far outside
                // the edge band when rotated and shears the whole page.
                if (row.height > 160)
                    return 0
                var cy = fl.contentY
                // binding dependency: re-evaluate on scroll
                var c = row.mapToItem(fl, 0, 0).y + row.height / 2
                if (c < btt.rollBand)
                    return (1 - Math.max(0, c) / btt.rollBand) * btt.rollMax
                var vh = fl.height
                if (c > vh - btt.rollBand)
                    return -Math.min(1, (c - (vh - btt.rollBand)) / btt.rollBand) * btt.rollMax
                return 0
            }
        }
    }
    function armRow(row, fl) {
        // Rows with an existing transform are either already armed or own
        // one of the app's few bespoke transforms; leave both alone.
        if (row.transform.length > 0)
            return
        row.transform = bttRollComp.createObject(row, {
            row: row,
            fl: fl
        })
    }
    function armRoll() {
        var fl = flick
        if (!fl || !fl.contentItem)
            return
        var ci = fl.contentItem
        for (var i = 0; i < ci.children.length; i++) {
            var it = ci.children[i]
            if (it.width < 100 || it.height < 25)
                continue
            // List views parent delegates directly to contentItem; the
            // column-based pages nest rows one level down in a page-sized
            // content column, which must not tilt as a whole. In both
            // cases only row-sized items are armed: shelf sections and
            // grid cells stay flat (the angle binding also re-checks the
            // cap live, for rows that grow after arming).
            if (it.height <= 160) {
                armRow(it, fl)
                continue
            }
            if (it.height < fl.height * 0.9)
                continue
            for (var j = 0; j < it.children.length; j++) {
                var row = it.children[j]
                if (row.width > 100 && row.height > 24 && row.height <= 160)
                    armRow(row, fl)
            }
        }
        // Rows may have moved (a fresh arm, a reflow, a returning tab), so
        // force every armed angle to recompute now, not on the next scroll.
        rollTick++
    }
    // Bump synchronously too: on a tab switch the returning pane is already
    // laid out, so its rows can re-tilt correctly in the same frame it
    // appears (no stale-then-correct flash); armRoll then re-checks post-layout.
    onFlickChanged: {
        btt.rollTick++
        Qt.callLater(armRoll)
    }
    Component.onCompleted: Qt.callLater(armRoll)
    // Delegates recycle and result columns repopulate; contentHeight moves
    // in both cases, so it doubles as the re-arm signal.
    Connections {
        target: btt.flick
        function onContentHeightChanged() {
            Qt.callLater(btt.armRoll)
        }
    }

    // the INLINE crest pill
    // The clipping band pins the pill's travel to the scroll viewport, so
    // it slides up UNDER the chrome edge when hiding, the same way rows
    // disappear when scrolled, instead of passing over the navbar.
    Item {
        x: btt.fX
        y: btt.fTop
        width: btt.fW
        height: 40
        clip: true
        visible: btt.live
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            y: btt.on ? 6 : -30
            width: bttRow.implicitWidth + 20
            height: 24
            radius: 12
            color: "#e6060810"
            border.color: bttMa.containsMouse ? btt.accent : btt.accentDim
            opacity: btt.on ? (bttMa.containsMouse ? 1 : 0.6) : 0
            visible: opacity > 0
            Behavior on opacity {
                NumberAnimation {
                    duration: 160
                }
            }
            Behavior on y {
                NumberAnimation {
                    duration: 200
                    easing.type: Easing.OutCubic
                }
            }
            Row {
                id: bttRow
                anchors.centerIn: parent
                spacing: 7
                Text {
                    id: bttCrest
                    textFormat: Text.PlainText
                    property int ph: 0
                    text: ("_.-~^~-._.~^'~._").substring(bttCrest.ph) + ("_.-~^~-._.~^'~._").substring(0, bttCrest.ph)
                    anchors.verticalCenter: parent.verticalCenter
                    color: btt.accent
                    font.family: btt.mono
                    font.pixelSize: 9
                    font.bold: true
                    font.letterSpacing: -1
                    Timer {
                        running: btt.on
                        interval: 120
                        repeat: true
                        onTriggered: bttCrest.ph = (bttCrest.ph + 1) % 16
                    }
                }
                Text {
                    textFormat: Text.PlainText
                    text: "TOP"
                    anchors.verticalCenter: parent.verticalCenter
                    color: btt.textHi
                    font.pixelSize: 9
                    font.bold: true
                    font.letterSpacing: btt.btnTrack
                }
            }
            MouseArea {
                id: bttMa
                anchors.fill: parent
                enabled: btt.on
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    bttAnim.stop()
                    bttAnim.target = btt.flick
                    bttAnim.from = btt.flick.contentY
                    bttAnim.start()
                }
            }
        }
    }
}

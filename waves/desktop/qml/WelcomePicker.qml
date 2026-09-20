import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "StatusLight.js" as StatusLight

// Provider welcome surface: the first-run gate, and the same cards
// re-opened as a non-blocking page from Settings -> Providers (or the
// "Finish setup" chip). One card per provider, from the descriptors the
// schema carries; Skip and the Apple card end the first-run state.
// Choosing TIDAL swaps the cards for its inline sign-in steps on this
// same surface: the browser opens only from the explicit OPEN BROWSER
// LOGIN click, CANCEL/Escape returns to the cards without answering
// anything, and a sign-in that is started never covers the app
// afterwards.
// `host` is Main.qml's root object, bound at both instantiations (the
// setup pane and the first-run gate) and required so a missed binding
// fails at load.
// It reads through it:
//   host.cancelSetupSignIn / host.providerCards / host.setupMode /
//   host.setupUrlOpened
//   host.accent / host.gold / host.red / host.textDim  the status-light
//     palette StatusLight.colorFor(host, state) reads for each step card's
//     state light (read through host, not copied locally, because the
//     helper takes a palette object)
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
Rectangle {
  id: pickCard
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color surface2: "#191c22"   // hover / nested
  readonly property color textDim: "#6b6f78"
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  implicitWidth: 480
  radius: 14
  color: surface2
  border.color: outline
  implicitHeight: pickCol.implicitHeight + 40
  signal picked(string provider)
  signal skipped
  ColumnLayout {
    id: pickCol
    anchors.fill: parent
    anchors.margins: 20
    spacing: 13
    WelcomeBanner {
      host: pickCard.host
      Layout.fillWidth: true
      Layout.preferredHeight: 75
    }
    // One card per registered provider, straight from the
    // descriptors: a provider the welcome has never heard of renders
    // through this same delegate.
    ColumnLayout {
      id: cardsCol
      objectName: "welcomeCards"
      Layout.fillWidth: true
      spacing: 13
      visible: host.setupMode === "cards"
      Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        textFormat: Text.PlainText
        text: "Choose where to start. You can enable the other provider later in Settings."
        color: textLo
        font.pixelSize: 13
      }
      Repeater {
        model: host.providerCards
        delegate: Rectangle {
          required property var modelData
          Layout.fillWidth: true
          radius: 10
          color: surface
          border.color: outline
          implicitHeight: pickRow.implicitHeight + 24
          RowLayout {
            id: pickRow
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            spacing: 12
            Image {
              objectName: "welcomeProviderLogo"
              Layout.alignment: Qt.AlignVCenter
              // RowLayout sizes children from their implicit
              // size (the PNG pixels) unless told otherwise:
              // plain width/height are ignored here.
              Layout.preferredWidth: modelData.logo_width !== undefined ? Number(modelData.logo_width) : 20
              Layout.preferredHeight: 20
              source: modelData.logo !== undefined ? String(modelData.logo) : ""
              fillMode: Image.PreserveAspectFit
              smooth: true
              cache: true
            }
            ColumnLayout {
              Layout.fillWidth: true
              spacing: 6
              Text {
                text: String(modelData.name)
                color: textHi
                textFormat: Text.PlainText
                font.pixelSize: 15
                font.weight: Font.DemiBold
              }
              Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: String(modelData.summary || "")
                textFormat: Text.PlainText
                color: textLo
                font.pixelSize: 12
              }
              // The provider's live state, where its
              // account is shown: the same
              // light shape the header marks read. A
              // provider with nothing to report (Apple
              // still off) shows no row.
              Row {
                objectName: "welcomeProviderStatus"
                visible: String(modelData.word || "") !== ""
                spacing: 7
                Rectangle {
                  width: 7
                  height: 7
                  radius: 3.5
                  anchors.verticalCenter: parent.verticalCenter
                  color: StatusLight.colorFor(host, String(modelData.state || ""))
                }
                Text {
                  textFormat: Text.PlainText
                  text: String(modelData.word || "")
                  color: textLo
                  font.pixelSize: 12
                }
              }
              // The action's words are the provider's own
              // (descriptor data): an Apple card offers a
              // one-time setup, never a sign-in (the
              // onboarding spec). A provider that
              // states none keeps the neutral invite.
              GateAction {
                objectName: "welcomeProviderAction"
                label: String(modelData.action || "") !== "" ? String(modelData.action).toUpperCase() : ("CONTINUE WITH " + String(modelData.name).toUpperCase())
                onClicked: pickCard.picked(String(modelData.id))
              }
            }
          }
        }
      }
      Text {
        objectName: "welcomeSkip"
        Layout.alignment: Qt.AlignHCenter
        textFormat: Text.PlainText
        text: "Not now"
        color: textDim
        font.pixelSize: 12
        font.underline: true
        // A reader's press answers the same skipped() the click calls.
        // Tab-reachable like every other primary control: the same
        // Return/Enter/Space acceptance GateAction carries, plus a focus
        // ring (a Text draws none itself).
        activeFocusOnTab: visible
        Accessible.role: Accessible.Button
        Accessible.name: "Not now"
        Accessible.onPressAction: pickCard.skipped()
        Keys.onReturnPressed: function (event) {
          if (!event.isAutoRepeat) {
            event.accepted = true
            pickCard.skipped()
          }
        }
        Keys.onEnterPressed: function (event) {
          if (!event.isAutoRepeat) {
            event.accepted = true
            pickCard.skipped()
          }
        }
        Keys.onSpacePressed: function (event) {
          if (!event.isAutoRepeat) {
            event.accepted = true
            pickCard.skipped()
          }
        }
        MouseArea {
          anchors.fill: parent
          anchors.margins: -6
          cursorShape: Qt.PointingHandCursor
          onClicked: pickCard.skipped()
        }
        Rectangle {
          anchors.fill: parent
          anchors.margins: -4
          radius: 6
          color: "transparent"
          border.width: 2
          border.color: "#3dff6e"
          visible: parent.activeFocus
        }
      }
    }
    // TIDAL's sign-in steps, inline on the same card. Step one is an
    // explicit click, the only caller of beginLogin; the paste field
    // and COMPLETE action appear with the redirect. Same
    // matrix-decrypt paste field as the search bar: a pasted redirect
    // URL auto-attempts sign-in once it has decoded in.
    ColumnLayout {
      id: signInCol
      objectName: "welcomeSignIn"
      Layout.fillWidth: true
      spacing: 13
      visible: host.setupMode === "tidal"
      RowLayout {
        Layout.fillWidth: true
        spacing: 10
        Text {
          textFormat: Text.PlainText
          text: "1"
          color: accent
          font.family: mono
          font.pixelSize: 12
          font.bold: true
          Layout.alignment: Qt.AlignTop
        }
        Text {
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          textFormat: Text.PlainText
          text: "Open the TIDAL login in your browser and sign in."
          color: textLo
          font.pixelSize: 13
        }
      }
      GateAction {
        objectName: "welcomeSignInOpen"
        label: host.setupUrlOpened ? "REOPEN BROWSER LOGIN" : "OPEN BROWSER LOGIN"
        onClicked: waves.beginLogin()
      }
      RowLayout {
        Layout.fillWidth: true
        spacing: 10
        visible: host.setupUrlOpened
        Text {
          textFormat: Text.PlainText
          text: "2"
          color: accent
          font.family: mono
          font.pixelSize: 12
          font.bold: true
          Layout.alignment: Qt.AlignTop
        }
        Text {
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          textFormat: Text.PlainText
          text: "Paste the URL you land on back here."
          color: textLo
          font.pixelSize: 13
        }
      }
      Rectangle {
        id: redirectBox
        objectName: "signInPaste"
        // The decoder is a non-visual QtObject, so scenarios reach
        // it through the box: they pin the decode animation
        // (decoding = true) while setting the field's text, then
        // release it before driving the visible COMPLETE SIGN-IN
        // action, since a submit while decoding stays quiet.
        readonly property var pasteDecoder: loginDecoder
        Layout.fillWidth: true
        implicitHeight: 44
        radius: 8
        color: surface
        visible: host.setupUrlOpened
        border.color: (redirectField.activeFocus || loginDecoder.decoding) ? accent : outline
        Behavior on border.color {
          ColorAnimation {
            duration: 160
            easing.type: Easing.OutQuad
          }
        }
        DecodeController {
          id: loginDecoder
          field: redirectField
          glyph: loginPaste
          onDecoded: function (text) {
            waves.completeLogin(text)
          }
        }
        RowLayout {
          anchors.fill: parent
          anchors.leftMargin: 12
          anchors.rightMargin: 6
          spacing: 8
          TextField {
            id: redirectField
            objectName: "signInField"
            Layout.fillWidth: true
            placeholderText: "Paste redirect URL here…"
            color: loginDecoder.decoding ? accent : textHi
            placeholderTextColor: textLo
            font.pixelSize: 13
            font.family: mono
            background: Rectangle {
              color: "transparent"
            }
            // A submit inside the decode window would send the scrambled
            // glyphs, never the link: the decode's own decoded() submits
            // the settled link, so a press meanwhile is already answered
            // and stays quiet instead of erroring spuriously.
            onAccepted: if (!loginDecoder.decoding)
              waves.completeLogin(text)
            onTextChanged: loginDecoder.noteTextChanged()
          }
          PasteGlyph {
            id: loginPaste
            Layout.alignment: Qt.AlignVCenter
            onClicked: {
              redirectField.forceActiveFocus()
              // A decode in flight holds the OLD link and would rewrite
              // the field back to it on its next tick: stop it before
              // the clear, or a second paste signs in with the first.
              loginDecoder.cancel()
              redirectField.clear()
              redirectField.paste()
            }
          }
        }
      }
      GateAction {
        objectName: "welcomeSignInComplete"
        visible: host.setupUrlOpened
        label: "COMPLETE SIGN-IN"
        // Same hold as the field's Enter: a click inside the decode
        // window would submit the scrambled glyphs (a spurious "that
        // isn't the sign-in link" before the real submit lands), so it
        // stays quiet and the decode's own submit carries the link.
        onClicked: if (!loginDecoder.decoding)
          waves.completeLogin(redirectField.text)
      }
      // The bridge's status line, shown inside the steps: the
      // status bar sits under the first-run gate's scrim, so this
      // is where "that isn't the sign-in link" is read.
      Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        textFormat: Text.PlainText
        visible: String(waves.status || "") !== ""
        text: String(waves.status || "")
        color: textLo
        font.family: mono
        font.pixelSize: 12
      }
      // The keyboard exit is the same: the Esc Shortcut above.
      GateAction {
        objectName: "welcomeSignInCancel"
        label: "CANCEL"
        neutral: true
        showArrow: false
        onClicked: host.cancelSetupSignIn()
      }
    }
  }
}

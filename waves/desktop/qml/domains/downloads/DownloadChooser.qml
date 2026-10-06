import QtQuick
import QtQuick.Controls.Basic
import "../../primitives" as Primitives
import "../providers"

// One anchored, scrollable comparison. Only the selected offer owns options.
Popup {
  id: chooser
  objectName: "chooserPopover"
  required property var control
  readonly property var button: control
  property double observedNow: Date.now()
  Timer {
    interval: 1000
    running: chooser.visible
    repeat: true
    onTriggered: chooser.observedNow = Date.now()
  }
  readonly property real windowLimitWidth: button.Window.window ? button.Window.window.width - 16 : 460
  readonly property real windowLimitHeight: button.Window.window ? button.Window.window.height - 16 : 640
  parent: control
  x: control.width - width
  y: control.height + 4
  margins: 8
  width: Math.min(460, windowLimitWidth)
  height: Math.min(body.implicitHeight + padding * 2, windowLimitHeight)
  padding: 12
  focus: true
  modal: false
  closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
  onOpened: {
    contentItem.forceActiveFocus()
    button.refreshOfferEvidence()
  }
  onClosed: {
    waves.cancelCatalogOffers(button.chooserOfferRequest)
    button.chooserEvidenceExpiry = 0
    button.chooserPendingSwitch = null
    control.forceActiveFocus()
  }
  function reveal(item) {
    if (!item.activeFocus)
      return
    var pos = item.mapToItem(body, 0, 0)
    var view = scroll.contentItem
    if (pos.y < view.contentY)
      view.contentY = pos.y
    else if (pos.y + item.height > view.contentY + view.height)
      view.contentY = pos.y + item.height - view.height
  }
  background: Rectangle {
    color: button.surfaceHi
    radius: 10
    border.color: button.outline
  }
  component Caption: Text {
    textFormat: Text.PlainText
    color: button.textLo
    font.family: uiFontFamily
    font.pixelSize: 11
    wrapMode: Text.Wrap
    width: parent.width
  }
  component Choice: Button {
    id: option
    property bool picked: false
    property int accessibleRole: Accessible.Button
    width: parent.width
    implicitHeight: Math.max(30, optionText.implicitHeight + 14)
    hoverEnabled: true
    activeFocusOnTab: chooser.visible && visible && enabled
    Accessible.role: accessibleRole
    Accessible.name: text
    Accessible.checkable: accessibleRole === Accessible.RadioButton || accessibleRole === Accessible.CheckBox
    Accessible.checked: picked
    Accessible.onPressAction: clicked()
    Accessible.onToggleAction: clicked()
    Keys.onReturnPressed: function (event) {
      if (!event.isAutoRepeat) {
        event.accepted = true
        clicked()
      }
    }
    Keys.onSpacePressed: function (event) {
      if (!event.isAutoRepeat) {
        event.accepted = true
        clicked()
      }
    }
    Keys.onEnterPressed: function (event) {
      if (!event.isAutoRepeat) {
        event.accepted = true
        clicked()
      }
    }
    onActiveFocusChanged: chooser.reveal(option)
    contentItem: Text {
      id: optionText
      textFormat: Text.PlainText
      text: option.text
      wrapMode: Text.Wrap
      color: option.picked ? button.accentContTx : button.textHi
      font.family: uiFontFamily
      font.pixelSize: 11
    }
    background: Rectangle {
      color: option.picked ? button.accentCont : button.surface3
      radius: 5
      border.color: option.activeFocus ? Primitives.Palette.accent : option.picked ? button.accentDim : button.outline
      border.width: option.activeFocus ? 2 : 1
    }
    ToolTip.visible: hovered
    ToolTip.text: text
    ToolTip.delay: 500
  }
  contentItem: ScrollView {
    id: scroll
    clip: true
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    Column {
      id: body
      width: scroll.availableWidth
      spacing: 8
      Caption {
        text: "DOWNLOAD WITH"
        color: Primitives.Palette.textDim
        font.bold: true
      }
      Caption {
        text: button.chooserProviderPinned ? "Provider pinned; engine choice is independent." : "Provider follows saved routing policy; origin is the default."
      }
      Repeater {
        model: button.chooserOffers
        delegate: Column {
          id: offerRow
          required property var modelData
          width: body.width
          spacing: 5
          readonly property bool selected: modelData.provider_id === button.chooserProvider
          readonly property var descriptor: modelData.descriptor || waves.providerDescriptor(modelData.provider_id)
          readonly property string providerName: descriptor ? descriptor.name : modelData.provider_id
          Choice {
            objectName: "chooserProviderOffer"
            property string providerId: offerRow.modelData.provider_id
            text: offerRow.providerName + (offerRow.selected ? " · selected" : " · compare")
            picked: offerRow.selected
            accessibleRole: Accessible.RadioButton
            onClicked: button.chooseProvider(offerRow.modelData.provider_id)
          }
          Row {
            width: parent.width
            spacing: 6
            ProviderBadge {
              descriptor: offerRow.descriptor
            }
            Caption {
              width: parent.width - 30
              text: "Match: " + (offerRow.modelData.match_state || "unknown").replace(/_/g, " ") + " · Delivery: " + (offerRow.modelData.readiness || "unknown").replace(/_/g, " ")
            }
          }
          Caption {
            text: offerRow.selected ? button.chooserEvidenceText : (offerRow.modelData.expires_at > 0 && offerRow.modelData.expires_at * 1000 <= chooser.observedNow ? "Availability stale; check again" : (offerRow.modelData.summary || "Exact availability unknown"))
            objectName: offerRow.selected ? "chooserAvailabilityEvidence" : "chooserOfferEvidence"
          }
          Caption {
            text: "Ownership: " + (offerRow.modelData.owned === true ? "Waves-owned Version" : offerRow.modelData.owned === false ? "not Waves-owned" : "unknown") + " · Library: " + (offerRow.modelData.library_present === true ? "present" : offerRow.modelData.library_present === false ? "absent" : "unknown")
          }
          Caption {
            visible: (offerRow.modelData.options && offerRow.modelData.options.engines || []).length > 0
            text: "Engine: " + (offerRow.selected ? button.chooserEngine : (offerRow.modelData.options ? offerRow.modelData.options.engine : "auto"))
          }
          Caption {
            visible: (offerRow.modelData.advertised || []).length > 0
            text: "Catalog advertised: " + (offerRow.modelData.advertised || []).map(function (f) {
              return (f.tier || "unknown tier") + " " + (f.audio_type || "")
            }).join(", ") + ". Exact delivery requires probe evidence."
          }
          Caption {
            visible: (offerRow.modelData.explanations || []).length > 0
            text: (offerRow.modelData.explanations || []).join(" ")
          }
          Choice {
            visible: (offerRow.modelData.readiness || "ready") !== "ready" && (offerRow.modelData.action || "") !== ""
            text: "Setup " + offerRow.providerName + ": " + (offerRow.modelData.action || "")
            onClicked: {
              button.closeChooser()
              waves.setupChooserProvider(offerRow.modelData.provider_id, offerRow.modelData.action)
            }
          }
          Loader {
            width: parent.width
            active: offerRow.selected
            sourceComponent: options
          }
          Rectangle {
            width: parent.width
            height: 1
            color: button.outline
          }
        }
      }
      Caption {
        text: button.chooserNotice
        visible: text !== ""
        color: button.gold
      }
      Choice {
        objectName: "chooserConfirmSwitch"
        visible: button.chooserPendingSwitch !== null
        text: "Confirm changes and switch provider"
        onClicked: button.confirmProviderSwitch()
      }
      Choice {
        visible: button.chooserPendingSwitch !== null
        text: "Keep current provider and choices"
        onClicked: {
          button.chooserPendingSwitch = null
          button.chooserNotice = ""
        }
      }
      Choice {
        objectName: "chooserCheckOffers"
        text: "Check offers again"
        onClicked: button.refreshOfferEvidence()
      }
      Choice {
        objectName: "chooserSetDefaults"
        text: "Set these options as provider defaults"
        onClicked: button.saveChooserAsDefaults()
      }
      Choice {
        objectName: "chooserConfirm"
        text: "Download with these options"
        enabled: button.chooserPendingSwitch === null
        onClicked: button.confirmChooser()
      }
      Caption {
        text: "Match confidence identifies the catalog item. Advertised, probed and selected facts are separate from verified delivered media. Preview keeps its own provider and duration."
        color: Primitives.Palette.textDim
      }
    }
  }
  Component {
    id: options
    Column {
      width: body.width
      spacing: 6
      Caption {
        text: "AUDIO QUALITY REQUIREMENT"
        visible: button.chooserTiers.length > 0
      }
      Repeater {
        model: button.chooserTiers
        delegate: Choice {
          objectName: "chooserTierRow"
          required property var modelData
          text: "Quality: " + modelData.word + " · " + (modelData.detail || "")
          picked: button.chooserTier === modelData.word
          accessibleRole: Accessible.RadioButton
          onClicked: button.chooserPickTier(modelData.word)
        }
      }
      Caption {
        text: button.chooserAtmosOnly ? "ATMOS ONLY" : "AUDIO TYPE"
      }
      Repeater {
        model: button.chooserAtmosOnly ? ["atmos"] : button.chooserAudioOptions
        delegate: Choice {
          objectName: "chooserAudioTile"
          required property string modelData
          text: "Audio type: " + modelData.toUpperCase()
          picked: button.chooserAudio === modelData
          accessibleRole: Accessible.RadioButton
          onClicked: button.chooserPickAudio(modelData)
        }
      }
      Caption {
        text: "ENGINE · " + (button.chooserExplicit.engine !== undefined ? "request choice" : "saved default")
        visible: button.chooserEngines.length > 0
      }
      Choice {
        objectName: "chooserEngineAuto"
        visible: button.chooserEngines.length > 0
        text: "Engine: Auto (provider preferences)"
        picked: button.chooserEngine === "auto"
        accessibleRole: Accessible.RadioButton
        onClicked: button.chooserPickEngine("auto")
      }
      Repeater {
        model: button.chooserEngines
        delegate: Column {
          required property var modelData
          width: body.width
          Choice {
            objectName: "chooserEngineChoice"
            text: "Engine: " + modelData.name
            picked: button.chooserEngine === modelData.id
            accessibleRole: Accessible.RadioButton
            onClicked: button.chooserPickEngine(modelData.id)
          }
          Caption {
            text: (modelData.requirements || []).map(function (r) {
              return r.operation + ": " + r.state + (r.action ? " · " + r.action : "")
            }).join("; ")
          }
        }
      }
      Repeater {
        model: [
          {
            key: "lyrics_embed",
            prop: "chooserLyricsEmbed",
            object: "chooserLyricsEmbed",
            label: "Embed lyrics",
            shown: button.chooserShowLyrics
          },
          {
            key: "lyrics_file",
            prop: "chooserLyricsFile",
            object: "chooserLyricsFile",
            label: "Save .lrc lyrics sidecar",
            shown: button.chooserShowLyrics
          },
          {
            key: "lyrics_ttml_file",
            prop: "chooserLyricsTtml",
            object: "chooserLyricsTtml",
            label: "Save verbatim .ttml lyrics sidecar",
            shown: button.chooserShowTtml
          },
          {
            key: "cover_embed",
            prop: "chooserCoverEmbed",
            object: "chooserCoverEmbed",
            label: "Embed album artwork",
            shown: button.chooserShowArt
          },
          {
            key: "cover_file",
            prop: "chooserCoverFile",
            object: "chooserCoverFile",
            label: "Save artwork sidecar",
            shown: button.chooserShowArt
          }
        ]
        delegate: Choice {
          required property var modelData
          objectName: modelData.object
          visible: modelData.shown
          text: modelData.label + (db[modelData.prop] ? " · on" : " · off")
          picked: db[modelData.prop]
          accessibleRole: Accessible.CheckBox
          onClicked: button.chooserToggle(modelData.key)
        }
      }
      Choice {
        objectName: "chooserAllowProviderFallback"
        text: "Allow provider fallback under saved policy"
        picked: button.chooserAllowProviderFallback
        accessibleRole: Accessible.CheckBox
        onClicked: button.chooserAllowProviderFallback = !button.chooserAllowProviderFallback
      }
      Choice {
        objectName: "chooserAllowEngineFallback"
        text: "Allow engine fallback under saved policy"
        picked: button.chooserAllowEngineFallback
        accessibleRole: Accessible.CheckBox
        onClicked: button.chooserAllowEngineFallback = !button.chooserAllowEngineFallback
      }
    }
  }
}

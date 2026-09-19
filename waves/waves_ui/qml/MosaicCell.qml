import QtQuick

// One quadrant of a tile mosaic: two stacked covers that crossfade when
// src changes (the first assignment fills in without a fade). Keeps the
// swap gentle, the tile never blinks to the background between covers.
// Split out of Main.qml (#315 slice 7).
Item {
  id: mc
  property string src: ""
  property bool _showingA: true
  Image {
    id: mcA
    anchors.fill: parent
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
    cache: true
    sourceSize.width: 200
    sourceSize.height: 200
    opacity: 1
  }
  Image {
    id: mcB
    anchors.fill: parent
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
    cache: true
    sourceSize.width: 200
    sourceSize.height: 200
    opacity: 0
  }
  onSrcChanged: {
    var front = _showingA ? mcA : mcB
    var back = _showingA ? mcB : mcA
    if (("" + front.source) === "") {
      front.source = src
      return
    }
    if (("" + front.source) === src)
      return
    back.source = src
    mcFade.stop()
    mcFadeIn.target = back
    mcFadeOut.target = front
    mcFade.start()
    _showingA = !_showingA
  }
  ParallelAnimation {
    id: mcFade
    NumberAnimation {
      id: mcFadeIn
      property: "opacity"
      to: 1
      duration: 900
      easing.type: Easing.InOutQuad
    }
    NumberAnimation {
      id: mcFadeOut
      property: "opacity"
      to: 0
      duration: 900
      easing.type: Easing.InOutQuad
    }
  }
}

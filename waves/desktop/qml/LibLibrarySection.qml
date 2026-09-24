import QtQuick
import QtQuick.Layouts

// The Library section (ADR 0007): the files the folder scan
// found on disk, the pane's first section and the one section that is not
// a provider's. Saved is the default view (the files carrying an on-disk
// Waves item id, each badged by that id's namespace); All files is every
// audio file the walk sees, where an untagged row carries no badge. Both
// views are the bridge's own (myMusicLibrary) and every page is the
// scan's (waves.loadLibraryFiles), so a signed-out pane still lists the
// library and its counts cannot disagree with the search badges. The
// section is never hidden: with no folder configured it says how to point
// Waves at one.
// `host` is Main.qml's root object, bound at its single instantiation
// (the My Music pane's first section) and required so a missed binding
// fails at load.
// It reads through it:
//   host.openLibrarySetting
// The file-row delegate passes it on to TrackRow (host: libSection.host),
// whose own contract reads the root.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes.
ColumnLayout {
  id: libSection
  required property var host
  // Waves palette (kept local so this file is self-contained, the
  // SettingsPage.qml convention) — copies of Main.qml's static literals.
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"

  // The bridge's shape: {configured, views: [{id, label}]}. An absent
  // answer reads as unconfigured, so the section explains itself
  // instead of rendering two empty lists.
  property var sectionData: ({})
  readonly property var views: sectionData.views || []
  readonly property bool configured: sectionData.configured === true
  // The visible view (Saved is the default, ADR 0007). Keep-alive per
  // view: rows, scroll, counts and pagination flags survive a flip.
  property string category: "saved"
  property var counts: ({})       // {view: total}
  property var more: ({})         // {view: hasMore}
  property bool loading: false
  property bool loadingMore: false
  // A scan that has not published yet is "still reading", never
  // "nothing found": the empty state must not claim an empty library
  // while the first sweep is running (see libraryScanStatus /
  // libraryIndexReady).
  property bool scanning: false
  property bool indexReady: true
  // A scan published while the pane was hidden: the rows and counts on
  // screen are from before it, so the section reloads on return
  // (see invalidate / ensureLoaded).
  property bool stale: false

  // The pane gives the section its share explicitly (see the usage in
  // libraryPane): a layout item that carries a size hint takes the
  // whole pane from its fill siblings, so this component never sets
  // its own fillHeight.
  Layout.fillWidth: true
  spacing: 0

  function countLabel(v) {
    var total = counts[v]
    return (total === undefined || total < 0) ? "" : " · " + total
  }
  function modelFor(v) {
    return v === "all" ? libAllModel : libSavedModel
  }
  function listFor(v) {
    return v === "all" ? libAllList : libSavedList
  }
  // Open the pane: load the visible view unless it already has rows,
  // and always when a scan published while the pane was hidden.
  function ensureLoaded() {
    if (!configured)
      return
    if (stale || listFor(category).count === 0)
      reload()
  }
  // A publish landed with the pane out of sight: remember it, do not
  // spend a page read on a list nobody is looking at.
  function invalidate() {
    stale = true
  }
  function reload() {
    if (!configured)
      return
    stale = false
    // A reload supersedes any in-flight append for this view (the
    // bridge drops the stale page), and pins the list's spot so a
    // refresh landing under the user keeps it (LibList's own
    // revalidate pattern).
    var lv = listFor(category)
    if (lv && lv.count > 0)
      lv.pendingY = lv.contentY
    loading = true
    loadingMore = false
    waves.loadLibraryFiles(category)
  }
  function select(v) {
    v = String(v || "")
    // The strip is bridge data, so an id it does not name is a wiring
    // bug: assigning it would blank the section (no list's visibility
    // gate would match). Only a known view switches.
    var known = false
    for (var i = 0; i < views.length; ++i) {
      if (String(views[i].id) === v) {
        known = true
        break
      }
    }
    if (v === category || !known)
      return
    category = v
    if (configured)
      reload()
  }
  // The library folder moved (a library pref committed, see Main.qml's
  // onLibrarySourceChanged): every row on screen belongs to the folder
  // being left, so they go, and the current view reloads from the new
  // folder (the section stays where the user was looking).
  function reset() {
    libSavedModel.clear()
    libAllModel.clear()
    counts = ({})
    more = ({})
    loading = false
    loadingMore = false
    if (configured)
      reload()
  }
  // A load's answer belongs to the view it was asked for, whichever
  // view is on screen when it lands: flipping mid-load must not lose
  // the rows (the bridge drops only genuinely stale ones).
  function applyLoaded(v, items, hasMore, total) {
    var model = modelFor(v)
    model.clear()
    for (var i = 0; i < items.length; ++i)
      model.append(items[i])
    var m = Object.assign({}, more)
    m[v] = hasMore === true
    more = m
    // The total is stored even when it is -1 (a failed page): the
    // section's status text reports it, so a read error must not read
    // as "no saved files yet".
    if (total !== undefined) {
      var c = Object.assign({}, counts)
      c[v] = total
      counts = c
    }
    if (v === category) {
      loading = false
      listFor(v).applyRestore()
    }
  }
  function applyMore(v, items, hasMore) {
    var model = modelFor(v)
    for (var i = 0; i < items.length; ++i)
      model.append(items[i])
    var m = Object.assign({}, more)
    m[v] = hasMore === true
    more = m
    // The rows land in their own view's keep-alive list either way,
    // but the spinner flag belongs to the VISIBLE view: a late append
    // for the view the user just left must not clear the one on
    // screen (see applyLoaded).
    if (v === category)
      loadingMore = false
  }
  function maybeLoadMore(view, cat) {
    if (cat !== category || !configured)
      return
    if (loading || loadingMore || more[cat] !== true)
      return
    var model = modelFor(cat)
    if (model.count === 0)
      return
    if (view.contentHeight - view.height - view.contentY > 600)
      return
    loadingMore = true
    waves.loadMoreLibraryFiles(cat, model.count)
  }
  // The one status the section shows in place of rows: the configure
  // ask, a read that failed, a scan still reading, or the view's own
  // empty sentence. A failed first page answers total -1 (see the
  // bridge), which must never read as "no saved files yet".
  function statusText() {
    if (!configured)
      return ""
    if (loading || listFor(category).count > 0)
      return ""
    if (counts[category] === -1)
      return "Could not read your music folder"
    if (scanning || !indexReady)
      return "Scanning your music folder…"
    return category === "all" ? "No audio files found" : "No saved files yet"
  }
  function statusHint() {
    if (!configured || loading || listFor(category).count > 0)
      return ""
    if (counts[category] === -1)
      return "Check the folder is available, then retry."
    if (scanning || !indexReady)
      return "Everything on disk appears here as the scan finds it."
    return category === "all" ? "Waves found no audio files in your music folder." : "Files Waves downloads land here, badged with the provider they came from."
  }
  function readScanState() {
    var st = ""
    try {
      st = String(waves.libraryScanStatus() || "")
    } catch (e) {
      st = ""
    }
    scanning = st === "scanning"
    try {
      indexReady = waves.libraryIndexReady() === true
    } catch (e) {
      indexReady = true
    }
  }
  Component.onCompleted: readScanState()
  Connections {
    target: waves
    function onLibraryScanStatusChanged() {
      libSection.readScanState()
    }
  }

  // Header: the pane's title (the section is always present, so the
  // title rides it) and the two views, mirroring a source group's strip.
  RowLayout {
    Layout.fillWidth: true
    Layout.leftMargin: 22
    Layout.rightMargin: 22
    Layout.topMargin: 2
    Layout.bottomMargin: 6
    spacing: 14
    Text {
      textFormat: Text.PlainText
      text: "My Music"
      color: textHi
      font.pixelSize: 18
      font.bold: true
      Layout.alignment: Qt.AlignVCenter
    }
    Item {
      // Definite width for the Flow (see LibSourceGroup's strip).
      Layout.fillWidth: true
      Layout.alignment: Qt.AlignVCenter
      implicitHeight: libViewsFlow.implicitHeight
      Flow {
        id: libViewsFlow
        objectName: "libViewsFlow"
        width: parent.width
        spacing: 8
        Repeater {
          model: libSection.views
          delegate: LibChip {
            required property var modelData
            objectName: "libViewChip-" + modelData.id
            label: modelData.label + libSection.countLabel(modelData.id)
            on: libSection.category === modelData.id
            onPicked: libSection.select(modelData.id)
          }
        }
      }
    }
  }

  Item {
    Layout.fillWidth: true
    Layout.fillHeight: true

    // One keep-alive pane per view: the LibList contract the source
    // groups use, so each view owns its rows, scroll and paging.
    LibList {
      id: libSavedList
      objectName: "libSavedList"
      cat: "saved"
      host: libSection
      model: libSavedModel
      delegate: libFileDelegate
      visible: libSection.configured && libSection.category === "saved"
    }
    LibList {
      id: libAllList
      objectName: "libAllList"
      cat: "all"
      host: libSection
      model: libAllModel
      delegate: libFileDelegate
      visible: libSection.configured && libSection.category === "all"
    }

    // No folder configured: the section explains the one click that
    // would fill it instead of disappearing (ADR 0007).
    Item {
      objectName: "libConfigureCta"
      visible: !libSection.configured
      anchors.fill: parent
      Column {
        id: libConfigureCol
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(parent.width - 44, 460)
        topPadding: 40
        spacing: 12
        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          textFormat: Text.PlainText
          text: "Point Waves at your music"
          color: textHi
          font.pixelSize: 18
        }
        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.WordWrap
          textFormat: Text.PlainText
          text: "Choose the folder Waves should scan and everything on disk shows up here, badged with the provider it came from."
          color: textLo
          font.pixelSize: 13
        }
        GateAction {
          objectName: "libConfigureAction"
          width: parent.width
          label: "Choose a music folder"
          onClicked: host.openLibrarySetting()
        }
      }
    }

    // Configured but nothing to show: the view's own empty state, or
    // the scan still reading. (The provider sign-in empty state below
    // is a different question and lives in libArea.)
    Item {
      objectName: "libFilesEmpty"
      visible: libSection.statusText() !== ""
      anchors.fill: parent
      Column {
        id: libFilesEmptyCol
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(parent.width - 44, 460)
        topPadding: 40
        spacing: 10
        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          textFormat: Text.PlainText
          text: libSection.statusText()
          color: textHi
          font.pixelSize: 18
        }
        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.WordWrap
          textFormat: Text.PlainText
          text: libSection.statusHint()
          color: textLo
          font.pixelSize: 13
          visible: text !== ""
        }
        GateAction {
          objectName: "libRetryAction"
          width: parent.width
          label: "RETRY"
          visible: libSection.statusText() === "Could not read your music folder"
          onClicked: libSection.reload()
        }
      }
    }
  }

  // The file row: TrackRow in its local mode (no catalog actions, the
  // provider badge instead of the quality picker), fed by the scan's
  // own row vocabulary.
  Component {
    id: libFileDelegate
    TrackRow {
      host: libSection.host
      required property var model
      width: ListView.view.width
      local: true
      provider: String(model.provider || "")
      providerLogo: String(model.provider_logo || "")
      folderPath: String(model.folder || "")
      tId: String(model.id || "")
      title: String(model.title || "")
      artistName: String(model.artist || "")
      album: String(model.album || "")
      year: String(model.year || "")
      date: ""
      duration: String(model.duration || "")
      durationSec: model.duration_sec || 0
    }
  }
  ListModel {
    id: libSavedModel
  }
  ListModel {
    id: libAllModel
  }
}

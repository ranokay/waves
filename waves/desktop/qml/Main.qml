import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Effects
import QtQuick.Shapes
import QtCore
import QtMultimedia
import "StatusLight.js" as StatusLight

ApplicationWindow {
  id: root
  // The bridge's signed-in flag, mirrored ONCE here. Every binding in this
  // file reads root.signedIn instead of waves.loggedIn: a read of a bridge
  // property is a call into Python (the interpreter must be taken, and at
  // launch the scan and network workers hold it), and the moment the flag
  // flips some three dozen bindings re-evaluate at once. One crossing here,
  // then plain QML reads everywhere else. The onLoggedInChanged handlers
  // below still ride the bridge signal itself.
  readonly property bool signedIn: waves.loggedIn
  // Starts hidden and is shown from Component.onCompleted once the saved
  // frame has been applied, so a remembered size/position takes
  // effect BEFORE the first present: the window opens where it was left with
  // no jump from the default frame. On a fresh install there is nothing to
  // restore and it shows at the default (4:3, 1040x780), centered on the
  // screen by onCompleted.
  visible: false
  width: 1040
  height: 780
  // Never allow a width that clips the header: the top bar's content
  // (logo, wordmark, nav tabs, queue, provider lights) sets the
  // real floor. headerRow reports 0 until it is laid out, hence the max.
  minimumWidth: Math.max(880, Math.ceil(headerRow.implicitWidth) + 44)
  minimumHeight: 560
  title: "Waves"
  color: bg

  // Album-art hover tilt knobs.
  // Variant: none | tilt | tilt_gloss | tilt_shadow. Tilt is BGT's value.
  // Lift is BGT's 1.04 swell cut by a fifth (0.04 -> 0.032): the cover read
  // as jumping toward you too eagerly at BGT's number.
  // Settings > Advanced > "Cover art tilts on hover". "none" is the same
  // switch the variants already had, so one binding turns the effect off
  // everywhere it reaches (Art, the track discs, the Browse hero cards).
  property bool artHoverTilt: waves.wavesPref("art_hover_tilt") !== false
  // Settings > Advanced > "Videos preview on hover". Off gates peekOpen, so
  // pointing at a thumbnail no longer grows the sound-on preview card; a
  // click still plays the video in full. An open peek closes on the flip.
  property bool videoHoverPeek: waves.wavesPref("video_hover_peek") !== false
  // Whether the library scan is on (saved state). The green done-state
  // button reads IN LIBRARY instead of DOWNLOADED while it is: with a
  // library in the picture "you have this" is the claim that matters, and
  // DOWNLOADED is just how the app happens to know it.
  property bool libraryOn: waves.wavesPref("library_enabled") === true
  // Whether fresh downloads land INSIDE the library folder. IN LIBRARY on a
  // done face is only honest when the library will actually contain the
  // file: either downloads land in the library (this flag) or the scan has
  // proven the copy present (libPresent per button). With a separate
  // download folder the face says DOWNLOADED, and moving the files into
  // the library flips it through the normal rescan.
  property bool dlInLibrary: waves.downloadsInsideLibrary() === true
  // per-item quality choices
  // Mirrored ONCE from the bridge, like the prefs above: media id -> tier
  // word, or "DEFAULT" for a track pinned to the setting under an album
  // that chose otherwise. A track without a choice of its own inherits its
  // album's, so choosing on an album turns every one of its track badges.
  property var qualityOverrides: waves.qualityOverrides || ({})
  // The Settings tier, the DEFAULT mark in every badge's menu.
  property string targetTier: waves.targetTier || ""
  function qualOverrideFor(mediaId, albumId) {
    var o = qualityOverrides
    var own = mediaId !== "" ? o[mediaId] : undefined
    if (own !== undefined && own !== "")
      return "" + own
    var inh = albumId !== "" ? o[albumId] : undefined
    return inh !== undefined && inh !== "" ? "" + inh : ""
  }
  // The ground a chosen tier's badge sits on: the tier's own container
  // colour, so a badge stating what YOU asked for reads apart from one
  // stating what the catalog offers (plain surface2).
  function qualTint(q) {
    return (q === "HI-RES" || q === "VIDEO") ? goldCont : q === "LOSSLESS" ? greenCont : q === "HIGH" ? cyanCont : surface3
  }
  // Chooser split button (spec §7.2)
  // Mirrored once: with Apple disabled every DownloadButton keeps today's
  // single-face behavior; with Apple enabled each gains its chevron face.
  property bool appleEnabled: false
  function refreshAppleEnabled() {
    try {
      root.appleEnabled = waves.isAppleEnabled() === true
    } catch (e) {
      root.appleEnabled = false
    }
  }
  Connections {
    target: waves
    function onQualityOverridesChanged() {
      root.qualityOverrides = waves.qualityOverrides || ({})
    }
    function onTargetTierChanged() {
      root.targetTier = waves.targetTier || ""
    }
    function onAppleStatusChanged() {
      root.refreshAppleEnabled()
    }
    function onQualityChoiceChanged(ids) {
      root.reopenDoneButtons(ids)
    }
    function onLibrarySourceChanged() {
      root.libraryOn = waves.wavesPref("library_enabled") === true
      root.dlInLibrary = waves.downloadsInsideLibrary() === true
      // The Library section's shape moves with the folder (a saved
      // configuration flips `configured`), so the pane's data re-reads
      // here, where the card's own commit announces the change, and the
      // section drops the rows of the folder it was showing.
      root.refreshMyMusicSources()
      libSection.reset()
    }
    function onArtHoverTiltChanged() {
      root.artHoverTilt = waves.wavesPref("art_hover_tilt") !== false
    }
    function onVideoHoverPeekChanged() {
      root.videoHoverPeek = waves.wavesPref("video_hover_peek") !== false
      if (!root.videoHoverPeek && root.peekNow)
        root.peekClose()
    }
  }
  property string artFxVariant: root.artHoverTilt ? "tilt" : "none"
  property real artFxTilt: 8
  property real artFxLift: 1.032
  // Whether the tilt springs or eases. OutBack overshoots at the end of
  // every move, which on the way back reads as the cover bouncing as it
  // lands flat; OutCubic settles straight into place. One knob, so the
  // covers and the track discs always move the same way.
  property int artFxEase: Easing.OutCubic
  // Artwork depth: hover shadow, and a resting raise while playing
  // Every cover that answers the pointer casts a shadow while it is
  // hovered, and artwork whose own preview is running stops answering the
  // pointer and settles slightly raised over that same shadow, so "what is
  // playing" reads from across the page without a badge or a colour
  // change. One shadow language for both states: a cover that starts
  // playing under the pointer deepens what is already there instead of
  // growing one out of nothing.
  // Held for the whole session on that cover, not just while sound is
  // coming out: a pause keeps the card up and sets the shadow breathing
  // (artPlayBreath) rather than dimming it, so a held cover reads as
  // resting, not as switched off.
  // Raise and shadow are deliberately small; this is a hierarchy cue, not
  // an animation.
  property real artPlayLift: 1.02          // resting swell while it plays
  property real artPlayShadowY: 10         // shadow drop while raised, px
  property real artPlayShadowBlur: 0.75    // MultiEffect blur, 0..1
  property real artPlayShadowA: 0.55       // shadow alpha at full depth
  property real artPlayBreath: 0.22        // paused: how far the breath relaxes
  property int artPlayBreathMs: 2400      // paused: one half-breath

  // Console palette (phosphor-green CRT, dark only)
  // Legacy names kept (values repointed) so every existing binding recolours
  // for free; new tokens add the gold / cyan / outline / surface-tier ideas.
  readonly property color accent: "#3dff6e"   // phosphor green (primary)
  readonly property color accentText: "#03210e"   // ink on a green fill
  readonly property color surface: "#15181d"   // primary card surface
  readonly property color surface2: "#191c22"   // hover / nested
  readonly property color border1: "#262a31"   // default card border (outline-variant)
  readonly property color line1: "#22262d"   // row dividers
  readonly property color textHi: "#e6e8ec"
  readonly property color textLo: "#a8acb4"
  readonly property color textDim: "#6b6f78"
  // New Console tokens
  readonly property color bg: "#0d0f12"
  readonly property color surface0: "#121418"   // topbar / statusbar / expand panel
  readonly property color surface3: "#1d2128"   // art bg / unlit meter / inset
  readonly property color surfaceHi: "#22262e"   // toast
  readonly property color outline: "#3a3f49"   // strong border (search / qtag / switch)
  readonly property color divider: "#22262d"
  readonly property color accentDim: "#22a64a"   // terminal-button border
  readonly property color accentCont: "#06210f"   // active chip / nav bg
  readonly property color accentContTx: "#86ffaa"   // text on accent container
  readonly property color gold: "#ffb01f"   // HI-RES / VIDEO tier + meter mid band
  readonly property color goldDim: "#b07d18"
  readonly property color goldCont: "#2a2008"
  readonly property color goldContTx: "#ffd27a"
  readonly property color green: "#3ef08a"   // LOSSLESS tier + done state
  readonly property color greenDim: "#2aa862"
  readonly property color greenCont: "#08230f"
  readonly property color greenContTx: "#8bf0b8"
  // "In your library" ownership badge: amber, deliberately distinct from the
  // green on-disk owned tag so the two ownership signals never blur.
  readonly property color libAccent: "#e5a00d"
  readonly property color libDim: "#9c6e0a"
  readonly property color libCont: "#241a05"
  readonly property color libContTx: "#f2c766"
  readonly property color cyan: "#56c8d8"   // HIGH tier + queued
  readonly property color cyanDim: "#3a8d99"
  readonly property color cyanCont: "#07232b"   // healthy-lossy pill container
  readonly property color cyanContTx: "#a6e7f1"
  readonly property color red: "#ff5a52"   // failed / peak / heart
  readonly property color redCont: "#2a0e0c"
  readonly property color redDim: "#b23f3a"   // small-lossy pill border
  readonly property color redContTx: "#ff9d97"
  readonly property string mono: monoFont    // bundled JetBrains Mono (see app.py)
  // Console button spec
  // One voice for every button/tab label: the native system sans, Bold,
  // UPPERCASE (nav tabs sentence case), lit-cell primaries; mono stays the
  // "data voice" (badges, numbers, ASCII art).
  readonly property string uiFont: uiFontFamily   // native system sans (see app.py)
  readonly property real btnTrack: 0              // label letter-spacing
  readonly property int btnRad: 8              // button corner radius
  // Outline weight for the download/preview controls (and the divider inside
  // the hover strip). A hair over 1px so the controls hold their edge against
  // busy artwork without reading as a heavy frame.
  readonly property real btnBorderW: 1.5
  readonly property int btnPadH: 12             // label padding, left/right
  readonly property int btnPadV: 7              // label padding, top/bottom
  readonly property color accentSoft: "#9dffbe"   // CRT flash / phosphor highlight

  // View routing
  // Exactly one main surface shows at a time: Browse (default), search
  // results, an artist page, My Music, or Settings. The booleans below are
  // the router; search results show when none of them are on.
  property string filterType: "all"     // search-results chip: all/artists/albums/...
  property var trackCache: ({})         // albumId -> [tracks], filled by albumTracksLoaded
  property var playlistTrackCache: ({}) // playlistId -> [rows], filled by playlistTracksLoaded
  property var artistsById: ({})        // artistId -> name, for link resolution
  property bool artistOpen: false
  property bool settingsOpen: false
  property bool libraryOpen: false
  // The provider welcome surface re-opened as a page (Settings -> Providers
  // or the "Finish setup" chip). The first-run presentation is the gate
  // below; this flag drives the non-blocking page variant.
  property bool setupOpen: false
  // The welcome surface's mode: "cards" (the provider choice) or "tidal"
  // (the inline sign-in steps). Cancel/Escape returns to the cards; a
  // completed sign-in closes the surface. Session state only, never
  // persisted: starting a sign-in is not a commitment.
  property string setupMode: "cards"
  // The explicit OPEN BROWSER LOGIN click happened in this signing, so the
  // paste steps (and their field) can appear. Set from onLoginUrlReady,
  // which only beginLogin emits; nothing else opens a browser.
  property bool setupUrlOpened: false
  // The live Apple light, refreshed on appleStatusChanged; the chip's
  // "can any provider download yet" test reads it.
  property var appleLight: ({})
  // The header's per-provider status lights and Browse's availability,
  // both composed by the bridge from the provider descriptors: the header
  // renders one mark per light, and Browse exists only
  // while a configured provider declares it. Re-read at boot and on the
  // same flips that move a session or the Apple light.
  property var providerLights: []
  // My Music's source groups and the pane's one empty state, composed by
  // the bridge from the provider descriptors and capabilities: a provider
  // that later declares FAVORITES appears in `sources`
  // with its own categories and no QML edit.
  property var myMusicSources: []
  property var myMusicEmpty: ({})
  // The Library section's shape (ADR 0007): its two views
  // (Saved first, the section's default) and whether a library folder is
  // configured. Provider-independent, so it is read with the other pane
  // data but never moves with a session.
  property var myMusicLibrary: ({})
  property var browseNav: ({
      available: false,
      signed_in: false
    })
  readonly property bool browseAvailable: !!(root.browseNav && root.browseNav.available)
  // The browse source's session, not the header's TIDAL flag: the bridge
  // names the provider that fills the pane, so the call to action follows
  // the source that would actually load it.
  readonly property bool browseSignedIn: !!(root.browseNav && root.browseNav.signed_in)
  // The welcome surface's provider cards (identity, copy, live status),
  // composed by the bridge from the descriptors. Re-read at boot and on
  // every flip that moves a session or the Apple light, and again when the
  // surface opens, so a card never states a stale account state.
  property var providerCards: []
  function refreshProviderLights() {
    try {
      root.providerLights = waves.providerLights()
    } catch (e) {
      root.providerLights = []
    }
  }
  function refreshProviderCards() {
    try {
      root.providerCards = waves.providerCards()
    } catch (e) {
      root.providerCards = []
    }
  }
  function refreshMyMusicSources() {
    var next = []
    try {
      next = waves.myMusicSources()
    } catch (e) {
      next = []
    }
    // Re-assign only on a real change: the pane's Repeater rebuilds its
    // groups when the array changes, so a setup flip that leaves the
    // sources as they were must not cost the pane its rows and scroll.
    if (JSON.stringify(next) !== JSON.stringify(root.myMusicSources))
      root.myMusicSources = next
    try {
      root.myMusicEmpty = waves.myMusicEmpty()
    } catch (e) {
      root.myMusicEmpty = ({})
    }
    try {
      root.myMusicLibrary = waves.myMusicLibrary()
    } catch (e) {
      root.myMusicLibrary = ({})
    }
  }
  // The provider surfaces always move together (a session or setup flip
  // changes the header's marks, the welcome cards and My Music's sources),
  // so one call keeps the BRIDGE.md rule in one place.
  function refreshProviderSurfaces() {
    root.refreshProviderLights()
    root.refreshProviderCards()
    root.refreshMyMusicSources()
    try {
      root.signInStepProviders = waves.providerSignInSteps()
    } catch (e) {
      root.signInStepProviders = []
    }
  }
  function refreshBrowseNav() {
    try {
      root.browseNav = waves.browseNav()
    } catch (e) {
      root.browseNav = {
        available: false,
        signed_in: false
      }
    }
  }
  // First-run welcome: nothing answered and nothing set up yet.
  readonly property bool welcomeDue: waves.sessionResolved && !signedIn && !waves.appleEnabled && !setupSettings.firstRunAnswered
  // The "Finish setup" chip: onboarding answered, but no provider can
  // download yet, and the user has not dismissed it.
  readonly property bool downloadsNeedSetup: setupSettings.firstRunAnswered && !signedIn && String(appleLight.state || "") !== "signed_in" && !setupSettings.setupChipDismissed
  // A newer release found by the updater (startup check or a manual one on
  // the Settings page). Drives the gold notice in the status bar's right
  // slot so the news is visible from any page, not just Settings.
  property bool appUpdAvailable: false
  property string appUpdLatest: ""
  // Browse is the launch view: the tab is open from the start, and the
  // landing page fetch fires as soon as login completes (onLoggedInChanged
  // re-fetches whenever the user is sitting on the Browse tab), or right
  // away below if the bridge finished its token login before QML loaded.
  property bool browseOpen: true

  // Window geometry persistence
  // Remember the window's size, position and maximized state across launches.
  // Saves route through the bridge's waves.json store (the channel every
  // other pref uses; it writes synchronously so it survives the standalone
  // os._exit teardown) and are debounced: a drag/resize fires a change per
  // pixel, so one settled write per gesture is enough. The NORMAL
  // (non-maximized) frame is tracked separately from the maximized flag so
  // un-maximizing lands on a sane size, and the backend clamps a restored
  // frame back onto a live screen. _geomReady gates saves so the restore
  // itself never triggers one, and so the initial show is not saved as a
  // change.
  property int _winNormalX: x
  property int _winNormalY: y
  property int _winNormalW: width
  property int _winNormalH: height
  property bool _geomReady: false
  function _winIsMax() {
    return visibility === Window.Maximized || visibility === Window.FullScreen
  }
  function _winCaptureNormalIfWindowed() {
    // Capture the normal frame only from a SETTLED windowed state, and only
    // at persist time (not on every raw geometry signal). On X11 a maximize
    // arrives as two independent, unordered events (the maximized
    // ConfigureNotify and the _NET_WM_STATE change); capturing eagerly could
    // record the transitional maximized geometry as the "normal" frame if
    // the geometry event landed first. By the time the debounce fires the
    // state has settled, so visibility here is coherent with the geometry.
    if (visibility === Window.Windowed) {
      _winNormalX = x
      _winNormalY = y
      _winNormalW = width
      _winNormalH = height
    }
  }
  function _winPersist() {
    if (!_geomReady)
      return
    // Don't persist while minimized/hidden: visibility collapses the
    // maximized substate to Minimized there, so a save would wrongly record
    // max=false, and there is no fresh frame to capture. The last
    // visible-state save stands, so maximize then minimize then quit still
    // restores maximized.
    if (visibility === Window.Minimized || visibility === Window.Hidden)
      return
    // Maximized keeps the last known normal frame (capture is skipped); only
    // the flag changes. windowSaveGeometry ignores a 0x0 teardown frame.
    _winCaptureNormalIfWindowed()
    waves.windowSaveGeometry(_winNormalX, _winNormalY, _winNormalW, _winNormalH, _winIsMax())
  }
  Timer {
    id: winGeomSaveTimer
    interval: 600
    onTriggered: root._winPersist()
  }
  onXChanged: if (_geomReady)
    winGeomSaveTimer.restart()
  onYChanged: if (_geomReady)
    winGeomSaveTimer.restart()
  onWidthChanged: if (_geomReady)
    winGeomSaveTimer.restart()
  onHeightChanged: if (_geomReady)
    winGeomSaveTimer.restart()
  onVisibilityChanged: if (_geomReady)
    winGeomSaveTimer.restart()
  onClosing: function (close) {
    _winPersist()
    // best-effort final flush; not the only save path
    // The drawer's width rides its own debounce, so a drag settled inside
    // the last interval would leave with the timer that never fired. Same
    // best-effort flush as the frame above, and the same guards behind it:
    // the bridge drops a save that changes nothing, and drops a zero.
    waves.queueSaveWidth(Math.round(root.queueWidth))
    // Downloads still running: veto the close and ask first. EXIT ANYWAY
    // re-closes with confirmed set, so this runs at most once per attempt.
    // Qt.quit() paths (factory reset) bypass by design: nothing to save.
    if (root.activeQueueCount > 0 && !setupSettings.exitWarnMuted && !exitGate.confirmed) {
      close.accepted = false
      exitGate.open = true
    }
  }

  Component.onCompleted: {
    // One-time onboarding seed: an existing user's answered picker keeps
    // them out of the welcome surface; the legacy key is cleared.
    setupSettings.migrateOnboarding()
    root.appleLight = waves.appleStatus()
    // Restore the saved window frame BEFORE the first present (see the
    // block above): apply the frame, seed the normal-frame trackers, then
    // show. The try/catch guarantees the window is shown even if the
    // restore hiccups, so a geometry glitch can never leave it hidden.
    var showMax = false
    var restored = false
    try {
      var g = waves.windowRestoreGeometry()
      if (g && g.w > 0 && g.h > 0) {
        root.x = g.x
        root.y = g.y
        root.width = g.w
        root.height = g.h
        root._winNormalX = g.x
        root._winNormalY = g.y
        root._winNormalW = g.w
        root._winNormalH = g.h
        showMax = g.maximized === true
        restored = true
      }
    } catch (e) {
      // fall through to a plain show
    }
    if (!restored) {
      // Nothing remembered yet: center the default 4:3 frame on the
      // screen instead of taking the OS's corner placement.
      root.x = Math.round(Screen.virtualX + (Screen.width - root.width) / 2)
      root.y = Math.round(Screen.virtualY + (Screen.height - root.height) / 2)
      root._winNormalX = root.x
      root._winNormalY = root.y
    }
    if (showMax)
      root.visibility = Window.Maximized
    else
      root.visible = true
    root._geomReady = true
    try {
      root.refreshAppleEnabled()
    } catch (e) {}
    root.refreshProviderSurfaces()
    root.refreshBrowseNav();

    // No configured provider fills Browse: the launch view falls
    // through to Search instead of a hidden tab's dead pane. With a
    // browse provider, Browse stays the launch view.
    if (!root.browseAvailable) {
      browseOpen = false
      navOrigin = "search"
    }
    if (root.signedIn && root.browseAvailable && browseSections.length === 0 && !browseLoading) {
      browseLoading = true
      waves.loadBrowse()
    }
    // An update staged in an earlier session that never got applied (the
    // swap helper gives up after a few hours, and a shutdown never wakes
    // it at all). No-ops unless something really is waiting; the answer
    // comes back on appUpdatePending.
    waves.resumePendingUpdate()
  }
  // The search payload's provider groups, in provider order.
  // The results page renders one SearchProviderGroup per entry, and every
  // root read of the page (counts, empty states, the sort) goes through it.
  property var searchGroups: []
  // Rows a payload's groups hold (the pinned top included): one sum for the
  // empty-state gate, the build veil's total and the page count.
  function searchRowTotal(groups) {
    var total = 0
    for (var i = 0; i < (groups || []).length; ++i) {
      var g = groups[i]
      total += (g.artists || []).length + (g.albums || []).length + (g.tracks || []).length + (g.videos || []).length + (g.playlists || []).length + (g.mixes || []).length + (g.top ? 1 : 0)
    }
    return total
  }
  // True once a search has populated any result model. Gates the filter chips
  // and the empty-state hint, so the chips materialize only after a search.
  readonly property bool hasResults: root.searchRowTotal(root.searchGroups) > 0
  // True only while a payload's groups are applied in place (a refresh):
  // each group's data handler picks reconcile over rebuild from this.
  property bool searchRefreshMode: false
  // The honest words when the last search's failure left them in its group
  // (the payload's `error`), shown in that group's own head and in the
  // empty line instead of a "0 results" that reads as an
  // empty catalog.
  readonly property string searchGroupError: {
    var groups = root.searchGroups || []
    for (var i = 0; i < groups.length; ++i) {
      var words = String(groups[i].error || "")
      if (words !== "")
        return words
    }
    return ""
  }
  function searchGroupList() {
    var out = []
    for (var i = 0; i < searchGroupRep.count; ++i) {
      var g = searchGroupRep.itemAt(i)
      if (g)
        out.push(g)
    }
    return out
  }
  function searchGroupFor(provider) {
    var want = String(provider || "")
    var groups = root.searchGroupList()
    for (var i = 0; i < groups.length; ++i)
      if (String(groups[i].providerId) === want)
        return groups[i]
    return null
  }
  // Apply one search payload's groups. A fresh search replaces
  // the list -- the empty step forces every group to rebuild, so the build
  // veil's Loaders tick exactly once per row -- while a refresh swaps the
  // rows of the groups the page already shows: it can neither mount nor
  // unmount a provider, so a refresh after a switch-off cannot put a ghost
  // head back.
  function applySearchGroups(groups, refresh) {
    groups = groups || []
    root.searchRefreshMode = refresh === true
    if (refresh === true) {
      var next = []
      for (var i = 0; i < root.searchGroups.length; ++i) {
        var current = root.searchGroups[i]
        var match = null
        for (var j = 0; j < groups.length; ++j)
          if (String(groups[j].provider) === String(current.provider)) {
            match = groups[j]
            break
          }
        next.push(match || current)
      }
      root.searchGroups = next
    } else {
      root.searchGroups = []
      root.searchGroups = groups
    }
    root.searchRefreshMode = false
  }
  // The provider's group leaves the page (Apple switching off): its rows and
  // its fold go with it, and a later refresh cannot put it back.
  function clearSearchGroup(provider) {
    var next = []
    for (var i = 0; i < root.searchGroups.length; ++i)
      if (String(root.searchGroups[i].provider) !== String(provider))
        next.push(root.searchGroups[i])
    if (next.length === root.searchGroups.length)
      return
    root.searchGroups = next
    if (searchBuilding)
      _searchBuildStart(0)
  }
  // The pinned rows read their clickable artists from the same side map the
  // section rows fill (appendMedia); the top item lands there too, but
  // register it here so a pin never depends on it. A fresh object each call:
  // the same reference assigned back notifies nothing, and every binding on
  // artistsById would keep its previous credits.
  function registerPinnedArtists() {
    var list = root.searchGroupList()
    var next = null
    for (var i = 0; i < list.length; ++i) {
      var top = list[i].topRow
      if (top && top.artists) {
        if (next === null)
          next = Object.assign({}, root.artistsById)
        next[top.id] = top.artists
      }
    }
    if (next !== null)
      root.artistsById = next
  }
  // The one rule for "a provider that can issue a search is live": the
  // search row and the build hint both follow it (the row is live for a
  // signed-out Apple-only user too). The bridge answers the generic half
  // (any registered SEARCH provider that is on), so a third
  // provider alone keeps the row live; the shipped two ride their reactive
  // flags so a sign-in or switch-off flips the row at once.
  readonly property bool searchAvailable: root.signedIn || root.appleEnabled || waves.searchEnabled()
  // The query as it is sent: every run of whitespace (a pasted line break
  // or tab the single-line field never shows) becomes one space.
  function searchQueryText(t) {
    return ("" + (t || "")).replace(/\s+/g, " ").trim()
  }
  // The last query submitted, and the one that answered with nothing: the
  // empty state then says so instead of still inviting a first search.
  property string lastSearchQuery: ""
  property string searchNoResultsFor: ""
  function submitSearch(q) {
    root._searchSeq = root._navSeq
    root.lastSearchQuery = q
    waves.search(q)
  }
  // ---- Search results / artist page / My Music ------------------------
  // Result rows live in the provider groups' own ListModels (declared in
  // SearchProviderGroup) and are replaced wholesale on each search; these
  // hold the sort order and per-page state around them.
  // Both halves of the sort control are pref-backed (search_sort by name,
  // search_sort_asc), so a launch opens on the order last chosen.
  property bool sortAsc: waves.wavesPref("search_sort_asc") === true
  readonly property var sortKeys: ["relevance", "date", "name", "popularity"]
  property bool bioExpanded: false
  // Default "home": the first My Music press of a session lands there, and
  // later presses return to whichever category this last held (openLibrary).
  property string libraryCategory: "home"
  // Album expand state lives here (keyed by album id) rather than inside each
  // AlbumBlock, so it survives ListView delegate recycling in the virtualised
  // My Music lists.
  property var expandedAlbums: ({})
  // Same, for the search PLAYLISTS rows (PlaylistBlock).
  property var expandedPlaylists: ({})
  // Expanding a row scrolls it up to this fraction of the viewport height
  // (a sliver of padding kept above), so the tracks it reveals are on
  // screen instead of below the fold. Scrolls down only: a row already
  // higher than the anchor line stays put.
  readonly property real expandAnchor: 0.10
  // Expanding and collapsing move two things at once: the panel folds and
  // the view scrolls. Both run on this one clock so the pair reads as a
  // single motion, instead of one landing after the other has stopped.
  readonly property int expandMoveMs: 280
  // Returns the scroll spot the view left behind when it did move, -1 when
  // the row was already high enough and nothing scrolled: the collapse
  // uses it to bring the view back (scrollCollapsedBack).
  function scrollExpandedIntoView(item) {
    var f = item.parent
    while (f && f.contentY === undefined)
      f = f.parent
    if (!f)
      return -1
    var y = item.mapToItem(f.contentItem, 0, 0).y
    var target = y - f.height * expandAnchor
    target = Math.max(0, Math.min(target, Math.max(0, f.contentHeight - f.height)))
    if (target <= f.contentY + 1)
      return -1
    var was = f.contentY
    expandScrollAnim.stop()
    expandScrollAnim.target = f
    expandScrollAnim.from = f.contentY
    expandScrollAnim.to = target
    expandScrollAnim.start()
    return was
  }
  NumberAnimation {
    id: expandScrollAnim
    property: "contentY"
    duration: root.expandMoveMs
    easing.type: Easing.OutCubic
  }
  // Where the view sat before an album or playlist row's expand pulled it
  // up to the anchor line, keyed by the row's id (the rows are recycled
  // delegates, so nothing is kept on them). Expanding a row scrolls the
  // rows above it out of the top of the view, so a collapse must return
  // the view to that spot, with the same motion the expand used: left
  // there, the rows the user had been looking at stay off screen and a
  // scroll back up is owed every time. Collapsing reads the spot back and
  // returns the view to it, so the row folds into the page it came out of.
  property var expandReturnY: ({})
  // Replacing the expanded set WHOLESALE (a page load, a Back restore, a new
  // search) drops every remembered spot with it. A spot belongs to the page
  // the row was expanded on: left behind, it outlives that page, and a later
  // collapse of a row with the same id glides the view to a contentY from a
  // page that is no longer there. Every wholesale write goes through here so
  // the pair can never come apart; AlbumBlock.toggle is the one writer that
  // keeps the spots, because it is the one that earns them.
  function resetExpandedAlbums(map) {
    expandedAlbums = map || ({})
    expandReturnY = ({})
  }
  function rememberExpandReturn(key, y) {
    if (y >= 0)
      expandReturnY[key] = y
  }
  function scrollCollapsedBack(key, item) {
    var y = expandReturnY[key]
    if (y === undefined)
      return
    delete expandReturnY[key]
    var f = item.parent
    while (f && f.contentY === undefined)
      f = f.parent
    if (!f)
      return
    // The view moved up past that spot since (the user scrolled back on
    // their own): there is nothing to return to.
    if (f.contentY <= y + 1)
      return
    expandScrollAnim.stop()
    expandScrollAnim.target = f
    expandScrollAnim.from = f.contentY
    expandScrollAnim.to = y
    expandScrollAnim.start()
  }
  // Collapsing a SHOW ALL section from deep inside it would otherwise leave
  // the view clamped to the page bottom, a random spot with no relation to
  // what was clicked. Land the view back at the section's header instead
  // (same padding sliver as expandAnchor), so SHOW LESS reads as returning
  // to the section you were browsing. Measured before the rows disappear
  // (the header sits above them, its y is unchanged by the collapse) and
  // applied via callLater, after the Column has relaid out, so the clamp
  // sees the new contentHeight; that still lands pre-paint (no visible
  // scroll). A view already above the section stays put.
  function scrollCollapsedToSection(item) {
    var f = item.parent
    while (f && f.contentY === undefined)
      f = f.parent
    if (!f)
      return
    var target = Math.max(0, item.mapToItem(f.contentItem, 0, 0).y - f.height * expandAnchor)
    if (f.contentY <= target + 1)
      return
    expandScrollAnim.stop()
    Qt.callLater(function () {
      f.contentY = Math.min(target, Math.max(0, f.contentHeight - f.height))
    })
  }
  // My Music is rendered as one group per bridge source: each
  // group owns its category strip, its sort, its pagination flags and its
  // keep-alive models, so a second provider's shelves are its own and no
  // state has to be keyed by (source, category) in here. These are the
  // roots of that routing: the Repeater's delegates (in registration order)
  // and the source -> group lookup every bridge emit goes through.
  function libGroupList() {
    var out = []
    for (var i = 0; i < libSourceRep.count; ++i) {
      var g = libSourceRep.itemAt(i)
      if (g)
        out.push(g)
    }
    return out
  }
  function libGroupFor(source) {
    var want = String(source || "")
    var groups = root.libGroupList()
    for (var i = 0; i < groups.length; ++i) {
      if (String(groups[i].sourceId) === want)
        return groups[i]
    }
    return null
  }
  // The view the scroll dressing follows: whatever the primary source's
  // visible shelf is (the top group is the pane's own). ``cat`` is passed in
  // so the caller's binding reads root.libraryCategory and re-evaluates
  // when the primary source switches shelves.
  function libActiveView(cat) {
    var groups = root.libGroupList()
    if (groups.length === 0)
      return null
    return groups[0].viewFor(String(cat || groups[0].category))
  }
  // Download-folder gate dialogs: the blocking "no folder set" gate and the
  // one-time soft nudge for users still on the old default. Driven by the
  // downloadFolderMissing / downloadFolderDefault signals.
  property bool folderGateBlocking: false
  property bool folderNudge: false
  // Advanced-settings reset confirmations. Both actions are destructive, so
  // nothing happens until the user confirms in these dialogs.
  property bool confirmSettingsReset: false
  property bool confirmFactoryReset: false
  // The set folder failed the reachability probe (NAS asleep, stale mount);
  // the download is held backend-side until Try again / a new folder.
  property bool folderUnreachable: false
  property string folderUnreachablePath: ""
  // FFmpeg missing at download time: the download is held backend-side
  // until the user sets FFmpeg up or explicitly continues degraded.
  property bool ffmpegBlocked: false
  property var artistData: ({})         // payload of the open artist page (artistLoaded)
  // Artist-page section collapse: persisted (prefs), so a section a user
  // folds away stays folded on every artist page until reopened. Album/EP
  // hunters shouldn't have to scroll past Top tracks on each visit.
  property bool artistTracksCollapsed: waves.wavesPref("artist_sec_tracks_collapsed") === true
  property bool artistAlbumsCollapsed: waves.wavesPref("artist_sec_albums_collapsed") === true
  property bool artistEpsCollapsed: waves.wavesPref("artist_sec_eps_collapsed") === true
  property bool artistVideosCollapsed: waves.wavesPref("artist_sec_videos_collapsed") === true
  function toggleArtistSection(which) {
    var v
    if (which === "tracks") {
      v = artistTracksCollapsed = !artistTracksCollapsed
    } else if (which === "albums") {
      v = artistAlbumsCollapsed = !artistAlbumsCollapsed
    } else if (which === "videos") {
      v = artistVideosCollapsed = !artistVideosCollapsed
    } else {
      v = artistEpsCollapsed = !artistEpsCollapsed
    }
    waves.setWavesPref("artist_sec_" + which + "_collapsed", v)
  }
  // Every artist-page section shows its first 5 (videos: whole rows) with a
  // SHOW ALL beneath it, exactly like the search page's mixed view, and a
  // section the user expands is remembered (prefs) across artists and
  // launches, per section, alongside the fold state the headers already
  // persist. Per-visit state would reset tracks and videos on every artist
  // change, and albums/EPs would have no memory of the choice at all.
  property bool topTracksExpanded: waves.wavesPref("artist_sec_tracks_expanded") === true
  property bool artistAlbumsExpanded: waves.wavesPref("artist_sec_albums_expanded") === true
  property bool artistEpsExpanded: waves.wavesPref("artist_sec_eps_expanded") === true
  property bool artistVideosExpanded: waves.wavesPref("artist_sec_videos_expanded") === true
  function toggleArtistExpand(which) {
    var v
    if (which === "tracks")
      v = topTracksExpanded = !topTracksExpanded
    else if (which === "albums")
      v = artistAlbumsExpanded = !artistAlbumsExpanded
    else if (which === "eps")
      v = artistEpsExpanded = !artistEpsExpanded
    else
      v = artistVideosExpanded = !artistVideosExpanded
    waves.setWavesPref("artist_sec_" + which + "_expanded", v)
  }
  // The search page (mixed All view) shows each section's first 5 results with
  // a SHOW ALL beneath it, so the page reads as a quick overview instead of a
  // wall. The fold and the SHOW ALL state live on each provider's own group
  // (SearchProviderGroup): pref-backed per provider and section,
  // so they survive a restart. A specific
  // section filter always shows everything (no cap).
  //
  // ARTISTS is the exception to the layout, and the layout is the provider's
  // own: a strip provider (TIDAL) collapses to a horizontal scroll strip of
  // fixed-size cards (a resize reveals more cards, never re-fits the ones on
  // screen, which is what keeps it smooth) and SHOW ALL expands it to a fill
  // grid; a flow provider (Apple, and the neutral default) caps its grid at
  // the mixed view's five. The group gates the two layouts' Loaders so
  // exactly one set is active, which keeps the build veil's
  // one-tick-per-artist accounting balanced.
  // A per-section cap for the mixed All view: the section's first 5 rows, or
  // everything once it is expanded; a specific section filter is never capped.
  // `cap` is the mixed view's default row count, 5 unless the section
  // says otherwise (the video grid rounds it up to whole rows).
  function searchRowVisible(name, count, index, expanded, cap) {
    return sectionVisible(name, count) && (filterType !== "all" || expanded || index < (cap || 5))
  }
  // Download state (mirrors the bridge)
  // mediaId -> a small reactive holder { real pct; string st }, created lazily
  // when a download for that id first reports. dlPct()/dlSt() read the holder;
  // the downloadProgress/downloadState handlers set exactly one holder's
  // property, so a progress tick re-binds only the controls showing THAT id.
  // (The previous whole-map reassignment invalidated the pct/state binding of
  // every instantiated download control on every tick, which under a burst of
  // per-segment ticks stole GUI-thread frames from scrolling and cover art.)
  property var dlHolders: ({})
  Component {
    id: dlHolderComp
    QtObject {
      id: dlh
      property real pct: -1
      property string st: ""
      // What the controls draw (dlPct reads it). It rides pct, but a
      // jump FORWARD of more than 3 points is filled at speed rather
      // than snapped: a resumed album or playlist opens with its owned
      // tracks skipped in one burst, so a forward jump must fill to
      // that point rather than snap.
      // LINEAR, and 200ms plus 22ms a point (1.5s at most): the bar's
      // blocks light in fill order, so a linear ramp lights them at an
      // even cadence and the eye follows the fill across. OutCubic over
      // 8ms a point would spend half the travel in the first fifth of
      // the ramp: at a glance the blocks all still arrive together. An
      // ordinary tick (a fraction of a point) lands at once, so a bar
      // that is merely downloading is untouched; a fall (a new run
      // resetting to -1 / 0) and the very first reading snap; with
      // hover motion off everything snaps.
      property real shownPct: -1
      property int rampMs: 0
      onPctChanged: {
        var d = pct - shownPct
        rampMs = (root.hoverMotion && shownPct >= 0 && d > 3) ? Math.min(1500, 200 + d * 22) : 0
        shownPct = pct
      }
      Behavior on shownPct {
        enabled: dlh.rampMs > 0
        NumberAnimation {
          duration: dlh.rampMs
          easing.type: Easing.Linear
        }
      }
    }
  }
  // In-app preview: exactly one preview plays at a time, addressed by
  // (previewKind, previewId), kind "track" or "artist". previewStopMs caps
  // playback (0 = whole track, the norm; a positive value clips it, same path).
  property string previewKind: ""
  property string previewId: ""
  property bool previewPlaying: false
  property bool previewLoading: false
  property int previewStopMs: 0
  // Live playback position/duration of the active preview (ms), for the artist
  // scrubber bar. 0 duration = not yet known.
  property int previewPosition: 0
  property int previewDuration: 0
  // True while a scrub gesture is in progress: the fill follows the cursor
  // and the player's own position clock is ignored, so exactly one real seek
  // fires (on release) instead of one per press/drag tick.
  property bool previewScrubbing: false
  property string previewNowTitle: ""
  property string previewNowArtist: ""
  property string previewNowArt: ""
  // Ids of the playing item, so the now-playing bar's track name opens its
  // album page (track highlighted) and its artist name opens the artist page.
  property string previewNowArtistId: ""
  property string previewNowAlbumId: ""
  property string previewNowTrackId: ""
  // Full credit list [{name, id}] so each collaborator in the now-playing bar
  // is separately clickable; falls back to the single primary artist.
  property var previewNowArtists: []
  // "kind:id" of the preview whose resolve just failed, flashes the button red
  // briefly (previewErrorTimer clears it), so a failed preview isn't silent.
  property string previewError: ""
  // Count of items still waiting/downloading (excludes done/failed/cancelled),
  // drives the header badge.
  property int activeQueueCount: 0

  // Download-queue grouping (Completed / Failed / Stopped / Downloading / Queued)
  // A finished row lingers 5s with its ✓ DONE chip, then slides up into the
  // collapsible Completed group. These counts feed the sticky section headers,
  // and each header pulses its own number when that number rises.
  // Which section header should pulse its count, and a tick to fire on. The
  // pulse is addressed to a SECTION, never to a header instance: the view
  // pools those and re-sections them as rows move between groups, so a
  // pulse started on the instance holding Completed at that instant can
  // play out on the same instance after it is handed to Downloading. A
  // header that is handed the pulse section after the tick re-arms on the
  // change, so the pulse follows the section however the pooled instances
  // swap.
  property string pulseSection: ""
  property int pulseTick: 0
  property bool completedCollapsed: true
  property int completedCount: 0
  // Failed rows get their own section (between Completed and Downloading)
  // whose header carries RETRY ALL; the count drives both.
  property int failedCount: 0
  property int downloadingCount: 0
  // Finished rows still lingering before their move to Completed; arms the
  // root lingerClock so the fold happens with the queue drawer closed too.
  property int lingerCount: 0
  // The rows STOP ended get a section of their own (between Failed and
  // Downloading) with the same RETRY ALL and CLEAR shape as Failed, so a
  // stop never reads as an error and a failure is never lost in a stop.
  property int stoppedCount: 0
  property int queuedCount: 0
  // Queue-row album expansion: which rows are open (by qid) and each row's
  // ordered per-track list ({qid: [{id,num,title,duration,status,pct}]}),
  // streamed live from the bridge while the album downloads.
  property var queueExpanded: ({})
  property var queueTracks: ({})
  // How many ledger rows an expanded queue row builds, and how many the
  // hover peek builds. Both are ceilings, not page sizes: the whole list is
  // already in queueTracks and every row's live state keeps arriving, these
  // only bound how many delegates exist. 500 covers any album and all but
  // the largest playlists in full; the peek only ever shows its top sliver.
  readonly property int queueLedgerMax: 500
  readonly property int queueLedgerPeek: 3
  // Queue drawer width, dragged by the handle on its own edge, and remembered
  // across launches the way the window frame is (0 is the never-saved
  // sentinel). 420 is the floor as well as the default: below it the quality
  // a row states and the title it states it for start fighting for the same
  // pixels. QueueDrawer reads it through its own clamp, so shrinking the
  // window pulls an over-wide drawer in rather than letting it hang off the
  // side, while what is STORED stays the width that was asked for.
  property real queueWidth: {
    var w = waves.queueRestoreWidth()
    return w > 0 ? w : 420
  }
  // One settled write per drag rather than one per pixel, same as the window
  // frame above. Restoring fires this too; the bridge drops a no-op save.
  Timer {
    id: queueWidthSaveTimer
    interval: 600
    onTriggered: waves.queueSaveWidth(Math.round(root.queueWidth))
  }
  onQueueWidthChanged: queueWidthSaveTimer.restart()
  // True while the drawer's resize edge is held. DotMatrix reads it to hold
  // its column rebuild until the hand has let go AND the release animation
  // has finished, so the one rebuild per gesture lands on a static screen.
  property bool queueEdgeHeld: false

  // Browse (TIDAL editorial pages)
  // The landing payload (content rows + the genre/mood/decade chip sets)
  // arrives via onBrowseLoaded; drilling a chip loads that page into
  // browsePage, keyed by its TIDAL api path so a slow load for a chip the
  // user has already left is ignored (see onBrowsePageLoaded).
  property var browseSections: []
  // The clicked card's own title, kept while its page payload is in flight,
  // so the breadcrumb (and a snapshot of a page left mid-load) can name the
  // page immediately instead of flashing the "Browse" fallback until
  // onBrowsePageLoaded fills browsePage.title in. Empty when the opener had
  // no title at hand; the trail then holds the crumb back entirely.
  property string browseTitleHint: ""
  // The clicked card's own cover, kept the same way while the payload is
  // in flight: the page hero paints it the frame the page is keyed (see
  // Art.underUrl) instead of waiting on the whole track list. Empty when
  // the opener had no cover at hand (a now-playing link, a video).
  property string browseArtHint: ""
  // Browse landing build veil
  // Fresh landing shelves incubate through asynchronous Loaders so the GUI
  // thread never freezes mid tab-strike, but the page must never be WATCHED
  // assembling: while building, the shelf loaders render at opacity 0
  // (heights still resolve) and the "Reading the wire…" hint stays up; when
  // the last loader reports ready the page appears complete in one paint,
  // exactly the pre-async look. Revalidations of a landing the user is
  // looking at, and endless-scroll growth, rebuild synchronously instead
  // (an in-place swap, no loading flash), so _browseAsyncBuild is set per
  // assignment by onBrowseLoaded / browseGrew.
  property bool _browseAsyncBuild: false
  property int _browseBuildTotal: 0
  property int _browseBuildReady: 0
  property bool browseBuilding: false
  function _browseBuildStart(n) {
    _browseBuildTotal = n
    _browseBuildReady = 0
    browseBuilding = n > 0
    if (browseBuilding)
      browseBuildGuard.restart()
    else
      browseBuildGuard.stop()
  }
  // A landing payload that arrived mid-handover, waiting for the reveal to
  // finish (see onBrowseLoaded and the end of bootHandover).
  property var _browseParked: null
  function applyBrowseLanding(p) {
    root.browseError = !!p.error
    var secs = p.sections || [];
    // Fresh build (nothing on screen): async + veil. Refresh of a landing
    // already showing: synchronous, swaps in place. While the launch
    // overlay is still up nothing is "showing" yet, and the boot-time
    // revalidate re-emit fires almost every launch because the landing
    // embeds For You rows (their ordering shifts between sessions), so
    // build that one asynchronously too: a synchronous shelf rebuild
    // freezes the GUI thread mid boot sequence and hitches the water/nav
    // animations.
    root._browseAsyncBuild = root.browseSections.length === 0 || !bootOverlay.done
    // +4 = the wayfinding groups (Playlists / Genres / Moods / Decades)
    // rendered as async shelves alongside the content sections.
    root._browseBuildStart(root._browseAsyncBuild && !p.error ? secs.length + 4 : 0)
    root.browseArtistsSideMap(secs)
    // Refresh of a landing already built: hold the spot across the
    // shelf rebuild (see holdScroll). The landing pane is alive even
    // behind a drilled page, and the clamp does not care that it is
    // hidden, so the hold arms regardless of which pane is showing.
    if (root.browseSections.length > 0)
      browseLanding.holdScroll()
    root.browseSections = secs
    root.browseChips = {
      genres: p.genres || [],
      moods: p.moods || [],
      decades: p.decades || []
    }
    // An open (or stacked) local: row page snapshotted a row this payload
    // may have just refreshed; bring it in line.
    root.refreshLocalBrowsePages(p.sections || [])
  }
  function _browseBuildTick() {
    if (!browseBuilding)
      return
    browseBuildGuard.restart()
    // progress: the guard watches for a STALL
    if (++_browseBuildReady >= _browseBuildTotal) {
      browseBuilding = false
      browseBuildGuard.stop()
    }
  }
  // A shelf's cards incubate behind their own asynchronous Loaders (see the
  // shelf ListViews), so a shelf reporting loaded is not the shelf being
  // painted: each card created while the veil is up joins the count, and
  // ticks when it lands, so the veil still drops on a finished page. Both
  // no-ops once the veil is down (a card scrolled into view later).
  function _browseCardStart(async) {
    if (async && browseBuilding)
      ++_browseBuildTotal
  }
  function _browseCardTick(async) {
    if (async)
      _browseBuildTick()
  }
  // A loader that errors (or a miscount) must never pin the veil. Re-armed
  // by every loader that reports, so this is an inactivity timeout, not a
  // budget for the whole build: a landing with a dozen shelves would blow
  // through a fixed 800ms and drop the veil mid-incubation, leaving the
  // rest of the page to arrive shelf by shelf.
  Timer {
    id: browseBuildGuard
    interval: 800
    onTriggered: root.browseBuilding = false
  }
  // Always-on freshness: revalidate-on-tab-return alone lets the landing
  // freeze for a user who parks on Browse. The backend's 60s throttle is a
  // floor (don't re-hit the API more often than this), not a ceiling, so
  // nothing forces a refresh while the tab just sits there. This timer is
  // that ceiling: while the Browse landing is the on-screen view, it re-pokes
  // the (throttled) revalidation on a cadence so New / For You track TIDAL
  // instead of staying pinned to the first load of a weeks-long session.
  // refreshBrowse repaints only on an actual change, so a quiet landing costs
  // one background request per tick and no visible flash. Bound to run only
  // when the landing is visible (browsePageKey === "" and no overlay), so
  // drill-in pages, other tabs and a backgrounded app make no requests.
  Timer {
    id: browseLandingFreshTimer
    interval: 5 * 60 * 1000    // max-age: editorial rows move a few times a day
    repeat: true
    running: root.signedIn && root.browseOpen && root.browsePageKey === "" && !root.settingsOpen && !root.libraryOpen && !root.artistOpen
    onTriggered: waves.refreshBrowse()   // silent, throttled; repaints only on change
  }
  // --- NEW mark on recent releases --------------------------------------
  // A release wears NEW for its first fortnight: two release Fridays, so a
  // weekly visit catches it and the mark stays rare enough to mean something.
  // The verdict is never stored. Payloads, and page_cache.json behind them,
  // carry only the release DATE, which does not decay; the comparison is
  // made here against a cutoff this clock moves, so a page parked for weeks
  // or restored from disk loses its marks on the right day with no
  // republish. ISO dates compare correctly as strings, so a row costs one
  // compare. Every surface asks isNewRelease; none compares dates itself
  // (tests/test_new_release_mark.py holds that).
  readonly property int newDays: 14
  // One breath of the NEW dot, in ms. Slow, so it reads as calm rather than
  // as an alert, and one shared beat, so every dot on screen breathes together.
  readonly property int newPulseMs: 3200
  // The oldest date still new, and tomorrow: a future-dated pre-release is
  // not new yet, and the extra day keeps timezone skew from hiding a release
  // that has already landed somewhere. Both "YYYY-MM-DD".
  property string newCutoff: ""
  property string newHorizon: ""
  function _isoDay(d) {
    return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2)
  }
  function refreshNewCutoff() {
    // Calendar arithmetic, not milliseconds: a fortnight that spans a DST
    // change is not 14 * 86400000 ms, and near midnight that slips a day.
    var t = new Date()
    var cut = root._isoDay(new Date(t.getFullYear(), t.getMonth(), t.getDate() - root.newDays))
    var hor = root._isoDay(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 1))
    if (cut !== root.newCutoff)
      root.newCutoff = cut
    if (hor !== root.newHorizon)
      root.newHorizon = hor
  }
  function isNewRelease(date) {
    var s = ("" + (date || "")).slice(0, 10)
    return s.length === 10 && root.newCutoff !== "" && s >= root.newCutoff && s <= root.newHorizon
  }
  Timer {
    id: newCutoffClock
    // Every minute: a sleeping Mac reports no change of any kind on wake,
    // so a slower clock left the mark up to its interval late after a
    // night asleep. The refresh is two date strings and writes nothing
    // unless the day moved.
    interval: 60 * 1000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refreshNewCutoff()
  }
  Connections {
    target: root
    // A window hidden across midnight corrects the moment it is shown.
    function onOnScreenChanged() {
      if (root.onScreen)
        root.refreshNewCutoff()
    }
  }
  // --- Search results build veil ----------------------------------------
  // Same treatment for a fresh search: every result card (artists, albums,
  // tracks, videos, playlists, mixes) incubates through an asynchronous
  // Loader while searchBuilding holds the pane at opacity 0 behind the
  // "Reading the wire…" hint, then the finished page appears in one paint.
  // The Loaders' asynchronous flag reads searchBuilding itself, so refills
  // outside a fresh search (the albums sort control) stay synchronous, an
  // in-place swap with no loading flash.
  property int _searchBuildTotal: 0
  property int _searchBuildReady: 0
  property bool searchBuilding: false
  // The library has not answered yet, so the badges the finished cards will
  // wear are not knowable and every pill would resolve to "not present".
  // Revealing here is what made a search during the first scan render bare
  // and then light every badge at once one frame later; the veil is already
  // up, so waiting costs nothing but the wait, and searchBuildGuard is still
  // the ceiling that ends it whatever the library is doing.
  property bool _searchAwaitingLibrary: false
  function _searchBuildStart(n) {
    _searchBuildTotal = n
    _searchBuildReady = 0
    _searchAwaitingLibrary = n > 0 && !waves.libraryIndexReady()
    searchBuilding = n > 0
    // A pending release from the PREVIOUS build would clear this one's wait
    // a pass after it started, revealing the new page unanswered.
    searchLibraryReveal.stop()
    if (searchBuilding)
      searchBuildGuard.restart()
    else
      searchBuildGuard.stop()
  }
  function _searchBuildTick() {
    if (!searchBuilding)
      return
    searchBuildGuard.restart()
    // progress: the guard watches for a STALL
    if (++_searchBuildReady >= _searchBuildTotal)
      _searchBuildMaybeReveal()
  }
  // Both conditions, from either side: the last card can finish before the
  // index publishes or after it, and whichever lands second drops the veil.
  function _searchBuildMaybeReveal() {
    if (!searchBuilding)
      return
    if (_searchBuildReady < _searchBuildTotal || _searchAwaitingLibrary)
      return
    searchBuilding = false
    searchBuildGuard.stop()
  }
  // A loader that errors (or a miscount) must never pin the veil, and neither
  // must a library that never answers. Re-armed by every loader that reports,
  // so this is an inactivity timeout rather than a budget for the whole
  // build: a full result set is well over a hundred async Loaders and would
  // blow through a fixed 800ms, dropping the veil mid-incubation so the rest
  // of the page (its badges included) arrives card by card.
  Timer {
    id: searchBuildGuard
    interval: 800
    onTriggered: {
      root._searchAwaitingLibrary = false
      root.searchBuilding = false
    }
  }
  // One event-loop pass between the library answering and the veil dropping,
  // so every badge on the page has re-resolved first (see the presence
  // handler for why the order is not free).
  Timer {
    id: searchLibraryReveal
    interval: 0
    onTriggered: {
      root._searchAwaitingLibrary = false
      root._searchBuildMaybeReveal()
    }
  }
  // The veil's visual: every veiled element binds its opacity to this one
  // animated value instead of the raw building flag, so when the veil drops
  // the whole page fades in quickly (over the ambient water, which stays
  // visible behind the "Reading the wire…" hint) rather than snapping in
  // as one hard paint. The animation runs in ONE direction only: raising
  // the veil for a new build snaps the value to 0 in the same frame. A
  // two-way Behavior here let the freshly refilled headers and SHOW ALL
  // links ghost-fade for 180ms over the loading hint on every new search,
  // a glitchy flash of half-transparent furniture between pages.
  property real searchReveal: 1
  onSearchBuildingChanged: {
    if (searchBuilding) {
      searchRevealRise.stop()
      searchReveal = 0
    } else
      searchRevealRise.restart()
  }
  NumberAnimation {
    id: searchRevealRise
    target: root
    property: "searchReveal"
    to: 1
    duration: 180
    easing.type: Easing.OutQuad
  }
  property real browseReveal: 1
  onBrowseBuildingChanged: {
    if (browseBuilding) {
      browseRevealRise.stop()
      browseReveal = 0
    } else
      browseRevealRise.restart()
  }
  NumberAnimation {
    id: browseRevealRise
    target: root
    property: "browseReveal"
    to: 1
    duration: 180
    easing.type: Easing.OutQuad
  }
  property var browseChips: ({
      genres: [],
      moods: [],
      decades: []
    })
  property bool browseLoading: false
  property bool browseError: false
  property var browsePage: null          // {key, title, sections} when drilled in
  property string browsePageKey: ""      // "" = the Browse landing page
  property bool browsePageLoading: false
  property bool browsePageError: false
  // "Is this album already in my local library?" for the album page on
  // screen, resolved synchronously from the scan index (null = no match or
  // index not built, badge hidden). Re-resolved whenever the page changes
  // and whenever the library scan publishes (onLibraryPresenceChanged).
  property var libraryPresence: null
  // Which published presence index this window's baked answers came from.
  // A browse payload is dressed with its library verdicts on a worker and
  // its cards are built from it later, so a publish in between leaves a
  // brand new card holding a verdict from before it, with the signal that
  // would have made it re-ask already fired. A card compares this against
  // the stamp baked into its own payload and asks live when they differ.
  // Read from the bridge ONCE per publish here, never per card: the whole
  // point of the dressing is that a card's creation makes no bridge call.
  property int libStamp: waves.libraryStamp()
  // browsePage is assigned from a dozen places (a fresh load, Back, forward,
  // a tab restore, a revalidate). Resolving presence only where the page is
  // LOADED left Back and tab-restore showing the previous album's badge on
  // this album, pointing at the wrong folder, so hang it off the property
  // itself: every assignment re-resolves, and nothing has to remember to.
  onBrowsePageChanged: root._resolveLibraryPresence()
  function _resolveLibraryPresence() {
    var ph = (root.browsePage && root.browsePage.header) ? root.browsePage.header : null
    root.libraryPresence = (ph && ph.kind === "album") ? waves.libraryAlbumPresence(ph.artist || "", ph.title || "", "" + (ph.year || ""), ph.num_tracks || 0, ph.duration_sec || 0) : null
  }
  property var browseStack: []           // pages beneath the current one (Back pops)
  property string browseHighlightId: ""  // track to highlight + scroll to on an album page
  // Opening an album by clicking one of its tracks scrolls the page down to that
  // row. Keep the page hidden (but laid out) until that scroll has been applied,
  // so the reader lands already on the track instead of watching it jump down,
  // matching every other navigation that drops you in place. The highlighted row
  // raises this as it lays out and lowers it once centred; the guard clears it if
  // the track never appears, so a page can never stay hidden.
  property bool browseHighlightPending: false
  onBrowseHighlightPendingChanged: if (browseHighlightPending)
    hiRevealGuard.restart()
  Timer {
    id: hiRevealGuard
    interval: 500
    onTriggered: root.browseHighlightPending = false
  }
  // Presentation: "art" = artwork-first (hero shelf, unframed covers, hover
  // download, genre/mood/decade colour tiles at the bottom, the streaming-
  // service look); "console" = chip sets up top + framed cards. Persisted.
  property string browseStyle: ("" + (waves.wavesPref("browse_style") || "art"))
  // Cover mosaics for the genre/mood/decade tiles: api path -> [urls],
  // streamed in by the backend's background sampler (see onBrowseTileArt).
  property var browseTileArt: ({})
  // True while the browse pane is being dragged/flicked. Cheap background
  // churn (tile-cover rotation) pauses during a scroll so the frame budget
  // goes to the scroll itself.
  property bool browseMoving: false
  // Tile-cover arrivals are buffered here and flushed on a timer: rebuilding
  // browseTileArt rebinds EVERY tile, and the sampler streams ~46 pages, so
  // coalescing turns dozens of full re-evaluations into a handful.
  property var _tileArtPending: ({})

  // Open-water launch dials
  // Driven by bootOverlay (end of file). The scrim starts light so the
  // water shows under the WAVES wordmark, and the interface starts hidden;
  // the launch sequence animates both to their resting values exactly once.
  property real bootScrimLevel: 0.55
  property real bootContentShown: 0
  // What the reveal actually paints. The dial above is the launch sequence's
  // own progress; this is the interface's share of it, and a pending terms
  // gate takes the whole frame instead: nothing of the app is painted or
  // reachable until the agreement is answered. Revealing the interface first
  // and dropping the card on top of it would leave the app fully readable,
  // and usable, by someone who has agreed to nothing. The gate rides the
  // same dial, so the wordmark's zoom fades straight into the card.
  readonly property real uiShown: termsGate.wanted ? 0 : bootContentShown
  // Paint the interface, invisibly, before the reveal needs it. The scene
  // graph skips a subtree whose opacity is 0 outright, so the first frame
  // that shows the interface pays for the whole page at once: every texture
  // upload, every glyph rastered, every material built. That bill landed
  // halfway through the wordmark zoom (the reveal starts 350ms into a 700ms
  // scale), which is the stutter that was seen, always at the same point
  // because the reveal always begins at the same point.
  //
  // Warming holds the interface a hair above the skip threshold (0.001)
  // during the version drain instead: far enough below perception to be
  // invisible over the scrim, far enough above zero for the renderer to do
  // the work. The drain is a text readout ticking on its own timer, so a
  // frame spent there costs nothing anyone can see, and by the time the
  // zoom starts every one of those caches is already warm.
  //
  // NOT wired to bootContentShown: that dial also ungates input, and the
  // interface must stay inert under the launch screen.
  property bool bootWarming: false

  // Ambient wave-loop background
  // A muted, seamlessly looping ocean video (public-domain loop, re-encoded
  // 720p) sits behind every page under a heavy scrim so the Console palette
  // and text contrast survive. z:-1 keeps it below all content; playback
  // pauses via presentStalled (see onPresentStalledChanged below) once
  // frames stop reaching the glass, which covers hidden/minimised too.
  Video {
    id: bgWave
    anchors.fill: parent
    z: -1
    // Settings > Advanced > "Motion background". An empty source (off)
    // tears down the whole decode pipeline, so disabled means zero cost.
    property bool motionOn: waves.wavesPref("motion_background") !== false
    visible: motionOn
    // Launch opens on the flat dark frame (wordmark and version only) and
    // the water fades in slowly underneath during the opening hold, timed
    // to be fully present as the zoom begins; the pipeline's first-frame
    // readiness gates it so there is never a pop. After boot (the motion
    // toggle, a stream restart) the fade is short.
    // (Video aliases hasVideo but not mediaStatus; hasVideo flips true
    // once the media is loaded, just before the first frame paints.)
    opacity: hasVideo ? 1 : 0
    Behavior on opacity {
      NumberAnimation {
        // InCubic keeps the opening frame essentially dark for the
        // first third of the fade, so the wordmark screen registers
        // before the water builds under it.
        duration: root.bootContentShown === 0 ? 1200 : 350
        easing.type: root.bootContentShown === 0 ? Easing.InCubic : Easing.InOutSine
      }
    }
    // The bridge serves a local cached copy of the bundled loop when one
    // exists (motionVideoUrl): streaming off the install volume during
    // boot starved the decoder and the water visibly stuttered.
    source: motionOn ? waves.motionVideoUrl() : ""
    loops: MediaPlayer.Infinite
    muted: true
    fillMode: VideoOutput.PreserveAspectCrop
    autoPlay: true
    onErrorOccurred: visible = false   // missing/undecodable asset: fall back to flat bg
    // Presentation continuity: the position of the last frame that
    // actually reached the glass (recorded per swap by onFrameSwapped).
    // While macOS holds presentation, the media clock keeps running, so
    // whenever frames return after a hold the loop seeks back here and
    // the water continues from the exact frame the user last saw.
    property int shownPos: 0
    function noteShown() {
      if (playbackState === MediaPlayer.PlayingState)
        shownPos = position
    }
    function seekShown() {
      if (!seekable || duration <= 0)
        return
      position = Math.min(Math.max(0, shownPos), duration - 40)
    }
    Connections {
      target: waves
      function onMotionBgChanged() {
        bgWave.motionOn = waves.wavesPref("motion_background") !== false
        bgWave.visible = bgWave.motionOn
        // undo a hide from a stale onErrorOccurred
        if (bgWave.motionOn)
          bgWave.play()
      }
    }
    Connections {
      target: root
      // One mechanism for every "nobody can see us" case: minimised,
      // hidden AND fully occluded (mere visibility misses occlusion, so
      // the loop would play on under the covering window and
      // re-expose would jump to a different frame). The clock has already
      // run for the detector's threshold by the time the stall trips,
      // so pausing alone would park the loop past the last visible
      // frame: pause, then seek back to that frame, and re-expose
      // presents it immediately before playback resumes.
      function onPresentStalledChanged() {
        if (!bgWave.motionOn)
          return
        if (root.presentStalled) {
          bgWave.pause()
          bgWave.seekShown()
        } else {
          bgWave.play()
        }
      }
    }
  }
  Rectangle {   // scrim: keeps the CRT-dark reading surface over the moving water
    id: bgScrim
    anchors.fill: parent
    z: -1
    visible: bgWave.motionOn
    color: root.bg
    // 0.93 is the resting value; the launch sequence holds it lighter so
    // the water reads through, then settles it here (see bootOverlay).
    opacity: root.bootScrimLevel
  }
  // The mouse's back and forward side buttons, taken here at the top of
  // the scene (above every page and popup) and nowhere else. A Python
  // event filter on the window would see EVERY event the window receives,
  // the per-frame update request included, and each of those crossings
  // waits for the interpreter behind whatever worker holds it: at launch
  // that wait is the single largest GUI-thread cost while the landing
  // builds, and the boot water drops frames on it. Only these two buttons
  // are accepted, so every
  // other press, wheel and hover passes straight through to the page. A
  // rapid pair is two taps (tapCount 1 and 2), both delivered, so nothing
  // is dropped.
  // A handler on a plain Item, not a MouseArea: an Item takes no press
  // it is not asked for, sets no cursor and takes no hover, so the page
  // beneath keeps its pointing hand and every other button.
  // It sits in the window's own content, so a modal popup's overlay is above
  // it and the side buttons do nothing while a dialog is open. That is the
  // wanted behaviour, not a gap: navigating the page underneath a modal
  // question is how you answer it by accident. Reviewed and deliberately
  // left alone.
  Item {
    anchors.fill: parent
    z: 1000000
    TapHandler {
      acceptedButtons: Qt.BackButton | Qt.ForwardButton
      gesturePolicy: TapHandler.ReleaseWithinBounds
      onTapped: function (point, button) {
        if (button === Qt.BackButton)
          root.navBack()
        else if (button === Qt.ForwardButton)
          root.navForward()
      }
    }
  }

  // One shared 20 Hz "breathe" clock for the next-to-fill cell in every LED
  // matrix (the download button, queue rows, progress bars). A per-frame
  // SequentialAnimation on each cell marks the whole window dirty every vsync;
  // with the full-window wave-loop video behind it, that recomposites the
  // entire scene at the display refresh for the whole download and pegs a CPU
  // core, the exact trap the WaveMark logo hit (see the note in WaveMark.qml).
  // Stepping one value at 20 Hz keeps the pulse visually identical while
  // repainting ~6x less. Cells bind opacity straight to ledPulse; when none
  // are pulsing nothing reads it, so the ticks cost nothing.
  property real ledPulse: 0.85
  // Companion phase for the "finishing" twinkle (bar at 100% while the
  // final steps run): each lit dot breathes on its own offset of this.
  // Same stepped-clock discipline as ledPulse, one write per tick; when no
  // bar is finishing nothing binds it, so it costs nothing.
  property real shimmerPhase: 0
  // Stepped tick counter for sequenced LED animations (the queued stack's
  // walking highlight): consumers derive their step from a base tick they
  // capture when they appear, so every instance starts its sequence from
  // the beginning. Same one-write-per-tick discipline as ledPulse; when
  // nothing is queued nothing binds it.
  property int marchTick: 0
  // The blinking terminal cursor, shared. A whole page of track discs can be
  // loading at once (the row window keeps ~70 alive), and one blink animation
  // per disc is the per-vsync repaint trap above. One derived value off
  // marchTick gives every mark the same 500ms on / 500ms off as the cover
  // box's own cursor, evaluated once per tick instead of once per disc.
  readonly property real termBlink: (marchTick % 20) < 10 ? 1 : 0
  // Presentation stall detector. When the window is fully covered (or
  // minimised/hidden), macOS stops asking it to render: frameSwapped goes
  // quiet while the media clock and every Timer keep running, so on
  // re-expose the water video and the ASCII clocks would snap to "now", a
  // visible jump to a completely different frame. Watch presentation
  // itself: no swap for ~½s means nobody can see us, pause the decorative
  // motion, and the first swap after re-expose resumes it from the exact
  // frame the user last saw. Any real repaint (input, progress, an
  // animation) keeps the swaps flowing, so a visible-but-idle window
  // cannot false-positive its own clocks off: those clocks only stop
  // once frames already stopped.
  property bool presentStalled: false
  // Seeded with "now", not 0: the detector below runs from t=0 and a zero
  // seed reads as an hours-old swap, latching a spurious stall during boot
  // before the first frameSwapped has been delivered.
  property double _lastSwap: Date.now()
  onFrameSwapped: {
    _lastSwap = Date.now()
    bgWave.noteShown()
    if (presentStalled)
      presentStalled = false
  }
  // True while frames are demonstrably reaching the glass. Only meaningful
  // with the wave video playing (its sink keeps swaps flowing whenever the
  // window is presented); video off, scenes legitimately go idle between
  // repaints and swap age says nothing, so the gate stands open.
  function presentFresh() {
    return bgWave.playbackState !== MediaPlayer.PlayingState || Date.now() - _lastSwap <= 120
  }
  Timer {
    interval: 400
    repeat: true
    running: true
    // 1.1s: comfortably past the ~0.6s presentation hiccup macOS causes
    // on every app-switch transaction, so only a genuinely covered or
    // minimised window trips the pause; the switch hiccup must ride
    // through undisturbed.
    onTriggered: if (Date.now() - root._lastSwap > 1100)
      root.presentStalled = true
  }
  // On screen = not hidden or minimised, and actually being presented.
  // Decorative clocks (this one, the WaveMark water, the browse ticker,
  // the login phrases) pause on THIS, never on window focus: an unfocused
  // window usually stays fully visible next to whatever stole focus, and
  // the water freezing the instant the app loses focus (then lurching
  // back on refocus) reads as a glitch.
  readonly property bool onScreen: visibility !== Window.Hidden && visibility !== Window.Minimized && !presentStalled
  Timer {
    running: root.onScreen
    interval: 50
    repeat: true
    property real phase: 0
    onTriggered: {
      // Hold the step while presentation is stalled (app-switch hold,
      // covered window): stepped state advancing unseen is exactly the
      // "jumps forward when frames return" glitch the water video had.
      if (!root.presentFresh())
        return
      phase = (phase + 0.05 / 1.04) % 1
      // 1.04s breathe = 2 x 520ms
      root.ledPulse = 0.28 + 0.57 * (0.5 + 0.5 * Math.cos(2 * Math.PI * phase))
      root.shimmerPhase = (root.shimmerPhase + 0.05 / 1.6) % 1
      // 1.6s twinkle cycle
      root.marchTick = (root.marchTick + 1) % 100000
    }
  }

  Timer {
    id: tileArtFlush
    interval: 220
    repeat: false
    onTriggered: {
      root.browseTileArt = Object.assign({}, root.browseTileArt, root._tileArtPending)
      root._tileArtPending = ({})
    }
  }
  function setBrowseStyle(s) {
    browseStyle = s
    waves.setWavesPref("browse_style", s)
  }
  // Shared by BrowseCard (console) and ArtCard (art) so both layouts speak
  // the same subtitle language and download dispatch.
  function cardSubtitle(card) {
    var kind = card.kind || ""
    return kind === "album" ? (card.artist || "") + (card.year ? "  ·  " + card.year : "") : kind === "playlist" ? (card.tracks > 0 ? card.tracks + " tracks" : (card.creator || "Playlist")) : kind === "mix" ? (card.subtitle || "Mix") : kind === "artist" ? "Artist" : (card.artist || "")
  }
  // Card captions render in two tones: the artist reads as a link (green),
  // the year / track-count metadata in white. Kinds with neither fall back
  // to the plain grey cardSubtitle.
  function cardSubLead(card) {
    var kind = card.kind || ""
    return kind === "album" || kind === "track" ? (card.artist || "") : ""
  }
  function cardSubMeta(card) {
    var kind = card.kind || ""
    return kind === "album" ? (card.listed || card.date || card.year || "") + "" : kind === "playlist" ? (card.tracks > 0 ? card.tracks + " tracks" : (card.creator || "Playlist")) : ""
  }
  // The artists a card caption should link: the per-artist array when the
  // payload carries one, else a single entry built from artist/artist_id
  // (ArtistLinks renders id-less names green but inert).
  function cardLeadArtists(card) {
    if (card.artists && card.artists.length > 0)
      return card.artists
    if (card.artist)
      return [
        {
          id: card.artist_id || "",
          name: card.artist
        }
      ]
    return []
  }
  function browseCardDownload(card) {
    var kind = card.kind || ""
    if (kind === "album")
      waves.downloadAlbum(card.id)
    else if (kind === "playlist")
      waves.downloadPlaylist(card.id)
    else if (kind === "mix")
      waves.downloadMix(card.id)
    else if (kind === "track")
      waves.downloadTrack(card.id)
    else if (kind === "video")
      waves.downloadVideo(card.id)
    else if (kind === "artist")
      waves.downloadArtist(card.id)
  }

  // The queue section's own word and count, for its header label and for the
  // spoken names of the actions riding it: several sections
  // carry a CLEAR and two carry a RETRY ALL, so each must say which section
  // it acts on.
  function queueSectionWord(section) {
    return section === "completed" ? "Completed" : section === "failed" ? "Failed" : section === "stopped" ? "Stopped" : section === "downloading" ? "Downloading" : "Queued"
  }
  // Dev timing: measure how long a section switch takes to process
  // markNav() stamps the start and arms a zero-interval Timer; the Timer fires
  // on the next GUI-thread event-loop turn, after the visibility bindings and
  // layout for the new section have been processed, and reports the elapsed
  // time to the backend dev log (see WavesBridge.uiLog / devlog.py). A Timer
  // (not the window's afterRendering signal) is used deliberately: afterRendering
  // runs on the scene-graph render thread, where calling a Python slot is unsafe.
  property string _navLabel: ""
  property double _navT0: 0
  property bool _navPending: false
  // Every user navigation flows through markNav, so it doubles as the bump
  // point for _navSeq: a counter that lets late search results detect the
  // user has moved on (see onSearchResults).
  property int _navSeq: 0
  // _navSeq's value at the moment the current search was issued.
  property int _searchSeq: -1
  function markNav(label) {
    _navSeq++
    markRender(label)
  }
  // A payload ARRIVING is not a navigation: it stamps the perf timer but must
  // never bump _navSeq. The Browse landing re-emits on every background
  // revalidate (near enough every launch, since the landing embeds the home
  // rows), and bumping there made onSearchResults discard the results the
  // user was waiting for: the status bar read "n results" while the pane
  // still showed the empty-state hint. Same for a late browse sub-page
  // payload, and for a results render (a second search typed right behind
  // the first must not look stale).
  function markRender(label) {
    _navLabel = label
    _navT0 = Date.now()
    _navPending = true
    navTimer.restart()
  }
  Timer {
    id: navTimer
    interval: 0
    repeat: false
    onTriggered: {
      if (root._navPending) {
        root._navPending = false
        waves.uiLog("nav", root._navLabel, Date.now() - root._navT0)
      }
    }
  }

  // Create-or-get the reactive holder for a media id (writers only). A new
  // holder bumps dlHoldersGen, which dlPct()/dlSt() read, so any control
  // already bound to them re-evaluates and starts tracking the new holder;
  // that rebind happens once per download start, not once per progress
  // tick. The map itself is only ever added to in place: cloning it per
  // notification would make every new download cost a copy of every holder
  // before it (a 10,000-album queue took 19 s of GUI thread just to be
  // queued).
  property int dlHoldersGen: 0
  function dlHolder(id) {
    var h = dlHolders[id]
    if (h === undefined) {
      h = dlHolderComp.createObject(root, {
        pct: -1,
        st: ""
      })
      if (h === null)
        return null
      dlHolders[id] = h
      dlHoldersGen += 1
    }
    return h
  }
  function dlPct(id) {
    var g = dlHoldersGen
    var h = dlHolders[id]
    return h !== undefined ? h.shownPct : -1
  }
  function dlSt(id) {
    var g = dlHoldersGen
    var h = dlHolders[id]
    return h !== undefined ? h.st : ""
  }
  // A quality choice landed on these ids (the item and, for an album, its
  // known tracks). A button reading DOWNLOADED because THIS session fetched
  // the item holds that word in its holder, past what ownership says; hand
  // it back so the button falls through to the ownership verdict, which
  // is judged against the choice: a copy below the chosen tier offers the
  // download again, a copy at or above it keeps reading DOWNLOADED. Only
  // "done" is touched: a queued or running item stays exactly as it is.
  function reopenDoneButtons(ids) {
    if (!ids)
      return
    for (var i = 0; i < ids.length; ++i) {
      var h = dlHolders[ids[i]]
      if (h !== undefined && h.st === "done")
        h.st = ""
    }
  }
  // The queue row a media id is waiting in, so a download button can cancel
  // its own wait without the queue drawer being opened. Walked on the click,
  // never bound: a queue of any size costs nothing until someone presses the
  // X. -1 = nothing of that id is waiting (it already started, or it is gone).
  function queuedQid(id) {
    if (!id)
      return -1
    for (var i = 0; i < queueModel.count; ++i) {
      var row = queueModel.get(i)
      if (row.media_id === id && row.status === "queued")
        return row.qid
    }
    return -1
  }
  function cancelQueuedMedia(id) {
    var qid = queuedQid(id)
    if (qid >= 0) {
      waves.cancelQueueItem(qid)
      return
    }
    // No row of its own: the id may be a ROLLUP (a discography, a folder
    // "download all"), one button standing over the N rows it queued. The
    // bridge knows which rows those are; it is a no-op for any other id.
    waves.cancelQueuedGroup(id)
  }

  // Flat list of every track/video id across a browse page's sections
  // (multi-disc albums split into one "tracks" section per disc). Feeds
  // DownloadButton.collectionIds so an album/playlist/mix header can show
  // DOWNLOADED once every member track is owned, the same live-checked way
  // a single track row already does.
  function collectionTrackIds(sections) {
    var ids = []
    var secs = sections || []
    for (var i = 0; i < secs.length; ++i) {
      var items = secs[i].items || []
      for (var j = 0; j < items.length; ++j) {
        if (items[j].id)
          ids.push(items[j].id)
      }
    }
    return ids
  }

  // In-app video player (simple modal overlay; first-ship scope)
  // videoNow: {id, title, artist} while the overlay is up, else null. The
  // backend resolves the stream URL asynchronously (waves.playVideo); the
  // overlay shows FETCHING until videoReady lands, then streams directly.
  property var videoNow: null
  property bool videoLoading: false
  property bool videoError: false
  property real videoPendingSeek: -1   // restore position across a quality switch
  property bool videoSwitching: false  // quality switch in flight, old stream keeps playing
  // The overlay can be driven by EITHER player: its own (a cold open from a
  // row) or the hover peek's, adopted mid-playback when the card is clicked
  // (see promoteVideo). Every control and readout in the overlay reads
  // vPlayer so it never has to care which pipeline is sounding.
  property bool videoFromPeek: false   // the overlay is showing the adopted peek pipeline
  property bool videoUpgrading: false  // real-quality stream loading behind that picture
  property bool videoOnB: false        // which of the two stacked sinks is on stage
  readonly property MediaPlayer vPlayer: videoFromPeek ? peekPlayer : videoPlayer
  function openVideo(id, title, artist) {
    if (!id)
      return
    peekClose()
    // the hover peek yields to the real player
    stopPreview()
    // one thing plays at a time
    videoPlayer.stop()
    videoPlayer.source = ""
    _videoStageReset()
    videoNow = {
      id: "" + id,
      title: title || "",
      artist: artist || ""
    }
    videoLoading = true
    videoError = false
    videoSwitching = false
    _videoSwapDone()
    waves.playVideo("" + id)
  }
  function closeVideo() {
    videoPlayer.stop()
    videoPlayer.source = ""
    videoUpgradeRetry.stop()
    videoUpgrading = false
    if (videoFromPeek) {
      peekPlayer.stop()
      peekPlayer.source = ""
      peekReady = false
    }
    videoFromPeek = false
    _videoStageReset()
    videoNow = null
    videoLoading = false
    videoError = false
    videoSwitching = false
    _videoSwapDone()
    vqMenu.visible = false
  }
  // Cold-open sink arrangement: the overlay's own player paints stage A,
  // the peek player owns the card's surface again.
  function _videoStageReset() {
    peekPlayer.videoOutput = peekSurface
    videoPlayer.videoOutput = vsA
    videoOnB = false
    videoOut.muted = false
    // an abandoned upgrade must never leave it silent
  }
  // Switch the running video to a newly chosen resolution as seamlessly as
  // Qt allows: the current stream KEEPS PLAYING while the new variant URL
  // resolves in the background; only once it arrives do we swap the source
  // and jump back to the live position (a sub-second hiccup, not a restart).
  // The choice persists app-wide (setVideoQuality writes the same setting
  // the Settings page does).
  function changeVideoQuality(h) {
    // A promotion upgrade is already a resolve in flight on this video;
    // a second one would race it (the menu is hidden while it runs).
    if (!videoNow || videoSwitching || videoUpgrading || videoFromPeek)
      return
    waves.setVideoQuality(h)
    videoSwitching = true
    waves.playVideo(videoNow.id)
  }

  // Peek to full player, without a gap
  // The peek's pipeline is ALREADY decoding this video, so the click never
  // opens a second stream and never restarts: the running player simply
  // hands its picture to the overlay's stage and keeps sounding. A frame
  // grabbed from the card covers the one-frame sink move. Behind that live
  // picture, the real-quality stream loads into the second (invisible)
  // stage and takes over once both are at the same moment, so the step up
  // in resolution costs nothing visible either (see _videoCut).
  function promoteVideo() {
    var p = peekNow
    if (!p || videoNow)
      return
    peekLinger.stop()
    // The grab lands on the next render (~a frame), while the card is
    // still showing the video, so the handover has something to hide
    // behind. If the platform refuses the grab, go without it.
    if (!peekSurface.grabToImage(function (result) {
      root._videoAdopt(p, result)
    }))
      _videoAdopt(p, null)
  }
  function _videoAdopt(p, grab) {
    if (!peekNow || peekNow.id !== p.id)
      // closed or retargeted mid-grab
      return
    stopPreview()
    if (grab) {
      _videoGrab = grab
      videoFreeze.source = grab.url
      videoFreeze.visible = true
      videoFreezeLift.restart()
    }
    videoNow = {
      id: p.id,
      title: p.title,
      artist: p.artist
    }
    videoLoading = false
    videoError = false
    videoSwitching = false
    videoPendingSeek = -1
    _videoSeekTarget = -1
    videoSeekRetry.stop()
    videoFromPeek = true
    videoUpgrading = true
    // Sinks trade places: the live peek takes the stage, the overlay's
    // own player parks on the invisible one to warm the upgrade there.
    videoOnB = false
    videoPlayer.videoOutput = vsB
    peekPlayer.videoOutput = vsA
    peekNow = null
    // the card goes away, its player does not
    waves.playVideo(p.id)
  }
  // Both pipelines are at the same moment: swap which one is on stage and
  // which one is audible, in a single frame, then retire the peek.
  function _videoCut() {
    videoUpgradeRetry.stop()
    videoUpgrading = false
    _videoUpPhase = 0
    if (!videoFromPeek)
      return
    var wasPaused = peekPlayer.playbackState !== MediaPlayer.PlayingState
    // The upgrade is parked on the very frame the peek is showing, so the
    // stage flip reveals a picture that is already correct. Retire the
    // glance stream first so the two never sound at once.
    videoOnB = true
    peekPlayer.stop()
    peekPlayer.source = ""
    peekPlayer.videoOutput = peekSurface
    videoOut.muted = false
    if (!wasPaused)
      videoPlayer.play()
    videoFromPeek = false
    peekReady = false
  }
  // The upgrade could not happen (no stream, or it failed): stay on the
  // peek's pipeline, which is playing perfectly well, just at glance
  // resolution. Nothing user-visible happens here.
  function _videoUpgradeGiveUp() {
    videoUpgradeRetry.stop()
    videoUpgrading = false
    _videoUpPhase = 0
    videoPlayer.stop()
    videoPlayer.source = ""
    videoOut.muted = false
  }
  // The peek's own pipeline died while it was driving the overlay. Take
  // the upgrade if it is ready, else surface the failure like a cold open.
  function _videoPromotionLost() {
    if (videoUpgrading && (videoPlayer.mediaStatus === MediaPlayer.LoadedMedia || videoPlayer.mediaStatus === MediaPlayer.BufferedMedia)) {
      _videoCut()
      return
    }
    videoUpgradeRetry.stop()
    videoUpgrading = false
    videoFromPeek = false
    peekReady = false
    _videoStageReset()
    videoLoading = false
    videoError = true
  }

  // Hover video peek (floating card, sound but no controls)
  // peekNow: {id, title, artist, art} while the card is up, else null. A
  // short dwell on a video thumbnail grows the card out of the thumb's
  // rect; the backend resolves a low variant (waves.peekVideo) and it
  // plays with sound until the pointer leaves. A click opens the full
  // player. This is a glance surface: no scrubber, no buttons, no chrome.
  property var peekNow: null
  property bool peekReady: false       // first frames are on the surface
  property bool peekThumbHover: false  // pointer is over the source thumb
  function peekOpen(anchor, id, title, artist, art) {
    if (!videoHoverPeek)
      // Settings > Advanced switched previews off
      return
    if (!id || videoNow)
      return
    if (peekNow && peekNow.id === ("" + id))
      return
    peekPlayer.stop()
    peekPlayer.source = ""
    peekReady = false
    var p = anchor.mapToItem(peekCard.parent, 0, 0)
    peekNow = {
      id: "" + id,
      title: title || "",
      artist: artist || "",
      art: art || ""
    }
    peekCard.growFrom(p.x, p.y, anchor.width, anchor.height)
    peekLinger.stop()
    waves.peekVideo("" + id)
  }
  function peekClose() {
    peekLinger.stop()
    peekPlayer.stop()
    peekPlayer.source = ""
    if (peekNow) {
      peekCooldown = true
      peekCooldownTimer.restart()
    }
    peekNow = null
    peekReady = false
  }
  // Brief rest after a peek ends before the next may start earning its
  // dwell, so glances across a grid of large thumbnails cannot chain-fire
  // stream requests (see BigVideoThumb).
  property bool peekCooldown: false
  Timer {
    id: peekCooldownTimer
    interval: 400
    onTriggered: root.peekCooldown = false
  }
  // The card lives while the pointer is over the thumb OR the card; when
  // both are gone a short grace covers the travel between them (and the
  // moment the growing card slides under the cursor).
  function peekHoverCheck() {
    if (!peekNow)
      return
    if (peekThumbHover || peekCardHover.hovered) {
      peekLinger.stop()
      return
    }
    peekLinger.restart()
  }
  Timer {
    id: peekLinger
    interval: 260
    onTriggered: root.peekClose()
  }

  // In-app preview control (single shared player, see previewPlayer)
  function pvActive(kind, id) {
    if (previewKind === kind && previewId === id)
      return true
    // Same underlying song, reached from a different surface: an artist/
    // album/playlist preview is always playing some concrete track, and
    // once the backend reports which one (previewNowTrackId) any track
    // control for that song adopts the live state, its art ring, row
    // bar, and card counter show pause/position instead of offering to
    // restart the very track that's already playing.
    return kind === "track" && previewKind !== "" && "" + id !== "" && "" + id === previewNowTrackId
  }
  // "" | "loading" | "playing" | "paused" | "error" for a given (kind, id).
  function pvSt(kind, id) {
    if (previewError === kind + ":" + id)
      return "error"
    if (!pvActive(kind, id))
      return ""
    return previewLoading ? "loading" : (previewPlaying ? "playing" : "paused")
  }
  // Fraction 0..1 of the active preview's playback (drives the scrubber fill).
  function pvFrac(kind, id) {
    if (!pvActive(kind, id) || previewDuration <= 0)
      return 0
    return Math.max(0, Math.min(1, previewPosition / previewDuration))
  }
  // stopMs: playback cap in ms (0 = whole track, the default intent; a positive
  // value caps the clip). Track art and the artist scrubber both pass 0, so a
  // preview spans, and seeks across, the full song.
  function startPreview(kind, id, stopMs) {
    if (!id)
      return
    peekClose()
    // a deliberate track preview outranks a hover glance
    previewStopMs = (stopMs === undefined ? 0 : stopMs)
    previewError = ""
    previewErrorTimer.stop()
    // Never inherit a pending seek-mute from the previous preview.
    seekUnmuteTimer.stop()
    previewOut.muted = false
    previewPlayer.stop()
    previewPlayer.source = ""
    previewKind = kind
    previewId = id
    previewLoading = true
    previewPlaying = false
    previewPosition = 0
    previewDuration = 0
    // Clear the now-playing metadata up front: it only refreshes when the
    // backend emits previewMeta after a multi-second resolve, so without this
    // the bar would keep showing the previous track (and open its artist).
    previewNowTitle = ""
    previewNowArtist = ""
    previewNowArt = ""
    previewNowArtistId = ""
    previewNowAlbumId = ""
    previewNowTrackId = ""
    previewNowArtists = []
    if (kind === "artist")
      waves.previewArtist(id)
    else if (kind === "album" || kind === "playlist" || kind === "mix")
      waves.previewMedia(kind, id)
    else
      waves.previewTrack(id)
  }
  // Click on the active preview toggles play/pause (or replays after a stop);
  // a click on a failed or on any other preview (re)starts it.
  function togglePreview(kind, id, stopMs) {
    if (previewError === kind + ":" + id) {
      startPreview(kind, id, stopMs)
      return
    }
    if (pvActive(kind, id)) {
      if (previewLoading)
        // still resolving, ignore taps (no source yet)
        return
      if (previewPlayer.playbackState === MediaPlayer.PlayingState)
        previewPlayer.pause()
      else
        previewPlayer.play()
    } else {
      startPreview(kind, id, stopMs)
    }
  }
  // Seek the active preview to a fraction 0..1 (scrubber click/drag). Updates
  // previewPosition optimistically so the fill tracks the cursor with no lag.
  function seekPreview(frac) {
    if (previewDuration <= 0)
      return
    var ms = Math.round(Math.max(0, Math.min(1, frac)) * previewDuration)
    previewPosition = ms
    // Mute across the seek. The FFmpeg backend flushes and re-primes its
    // decoder on a position change, which stutters/pops as playback picks
    // back up; a brief mute (lifted by seekUnmuteTimer once the pipeline has
    // re-synced) hides that so audio returns cleanly, mid-track.
    previewOut.muted = true
    previewPlayer.position = ms
    seekUnmuteTimer.restart()
  }
  // Lifts the seek mute after the backend has settled on the new position.
  Timer {
    id: seekUnmuteTimer
    interval: 160
    onTriggered: previewOut.muted = false
  }
  // Drag feedback only: move the fill without touching the player. Seeking
  // the FFmpeg backend mid-gesture flushes and restarts its audio output,
  // audible as a pop/double-start, so the actual seek is deferred to the
  // one seekPreview call on release, leaving the drag silent and smooth.
  function scrubPreviewVisual(frac) {
    if (previewDuration <= 0)
      return
    previewPosition = Math.round(Math.max(0, Math.min(1, frac)) * previewDuration)
  }
  function stopPreview() {
    seekUnmuteTimer.stop()
    previewOut.muted = false
    previewPlayer.stop()
    previewPlayer.source = ""
    previewPlaying = false
    previewLoading = false
    previewKind = ""
    previewId = ""
    previewPosition = 0
    previewDuration = 0
    previewNowTitle = ""
    previewNowArtist = ""
    previewNowArt = ""
    previewNowArtistId = ""
    previewNowAlbumId = ""
    previewNowTrackId = ""
    previewNowArtists = []
  }
  // Now-playing bar (bottom status bar) controls
  // Play/pause the shared player without touching which item is active, so the
  // bar keeps working after the user navigates away from the source row.
  function nowToggle() {
    if (previewKind === "" || previewLoading)
      return
    if (previewPlayer.playbackState === MediaPlayer.PlayingState)
      previewPlayer.pause()
    else
      previewPlayer.play()
  }
  function nowStop() {
    stopPreview()
  }
  // Now-playing bar: the track name opens the album page with the track
  // highlighted (fade), falling back to the artist page if there's no album
  // id. Each artist name links to its own page inline (see the bar itself).
  function nowOpenAlbum() {
    if (previewNowAlbumId !== "")
      openAlbumPage(previewNowAlbumId, previewNowTrackId, "", previewNowArt)
    else if (previewNowArtistId !== "")
      waves.loadArtist(previewNowArtistId)
  }
  // "M:SS" from milliseconds, for the scrubber time readout.
  function fmtMs(ms) {
    if (!(ms > 0))
      return "0:00"
    var s = Math.floor(ms / 1000)
    var m = Math.floor(s / 60)
    var r = s % 60
    return m + ":" + (r < 10 ? "0" + r : "" + r)
  }
  // Clears the red error flash a couple of seconds after a failed resolve.
  Timer {
    id: previewErrorTimer
    interval: 2500
    onTriggered: root.previewError = ""
  }

  // ATMOS is a KIND of file, not a rung on the gold/green/cyan ladder, and it
  // must not read as one: a Dolby Atmos copy is delivered at one fixed tier
  // the audio quality setting cannot raise, so there is no better Atmos to
  // want. It therefore wears none of the ladder's colours and none of its
  // ground. Outline only, plain ink, the same filled dot every tier pill
  // draws, and SPATIAL where a tier states its spec. Same word, same ink, on
  // every surface that shows a quality, from the search row to the queue
  // drawer's tier column.
  function qualBg(q) {
    return q === "ATMOS" ? "transparent" : surface2
  }
  function qualFg(q) {
    return (q === "HI-RES" || q === "VIDEO") ? gold : q === "LOSSLESS" ? green : q === "HIGH" ? cyan : q === "ATMOS" ? textHi : textLo
  }
  function qualBorder(q) {
    return (q === "HI-RES" || q === "VIDEO") ? goldDim : q === "LOSSLESS" ? greenDim : q === "ATMOS" ? textDim : outline
  }
  function qualDot(q) {
    return q === "LOW" ? textDim : qualFg(q)
  }
  // Standard spec for each TIDAL quality tier (the exact hi-res sample rate
  // isn't exposed without a per-track stream lookup, so we show the tier's
  // baseline: lossless is always FLAC 16-bit/44.1kHz, hi-res is 24-bit FLAC).
  function qualSpec(q) {
    return q === "HI-RES" ? "24-bit" : q === "LOSSLESS" ? "16/44.1" : q === "HIGH" ? "AAC 320" : q === "LOW" ? "AAC 96" : q === "VIDEO" ? "1080p" : q === "ATMOS" ? "SPATIAL" : ""
  }
  function qualSpecFg(q) {
    return (q === "HI-RES" || q === "VIDEO") ? goldContTx : q === "LOSSLESS" ? greenContTx : q === "HIGH" ? "#a6e7f1" : textLo
  }
  function statusColor(s) {
    return s === "running" ? accent : s === "done" ? accent : s === "failed" ? red : s === "queued" ? cyanDim : textLo
  }
  function sectionVisible(name, count) {
    return count > 0 && (filterType === "all" || filterType === name)
  }

  function segColor(i) {
    return i < 5 ? green : i < 8 ? gold : red
  }

  // Back/forward navigation (triggered by the back bar, the native swipe
  // gesture, or the mouse side buttons, detected app-side in
  // WavesBridge.eventFilter; the swipe gesture stays back-only).
  // Navigation history
  // Swipe-back / back bars return to where you actually WERE (search page,
  // a genre page, an artist), not to a fixed hierarchy. Each view change
  // pushes a snapshot of the view being left; navBack() pops and restores
  // it, pushing the left view onto navForwardHistory so navForward() can
  // return to it.
  property var navHistory: []
  property var navForwardHistory: []
  property bool _navRestoring: false
  // Armed by navBack when the target artist must be re-loaded: onArtistLoaded
  // resets the expansion state on every full load, so a Back re-applies the
  // snapshot's state ({id, ex, bio}) from here instead. The matching
  // scroll restore is armed on artistView (pendingRestoreKey/Y), pre-paint.
  property var _artistRestoreState: null
  // Which top-level section the user is "in" for the nav tabs: drilling into
  // an artist or album page keeps the tab of the section it was opened from
  // lit (to the user they never left Browse/Search/My Music). Only explicit
  // section switches (tab clicks, a new search, Back/Forward across sections)
  // move it.
  property string navOrigin: "browse"
  function navSig(s) {
    return s.v + "|" + (s.key || "") + "|" + (s.id || "") + "|" + (s.cat || "")
  }
  function navSnapshot() {
    if (settingsOpen)
      return {
        v: "settings",
        label: "Settings"
      }
    if (libraryOpen)
      return {
        v: "library",
        cat: libraryCategory,
        label: "My Music"
      }
    if (artistOpen)
      return {
        v: "artist",
        id: artistData ? "" + artistData.id : "",
        label: artistData ? (artistData.name || "Artist") : "Artist",
        // Which of the artist's TWO pages this is. My
        // Music opens a library-scoped one through the
        // same signal, with the same id, holding only
        // the favourites; without this the restore
        // below reads them as one page and a Back off
        // the scoped page is a dead press that eats
        // its history entry. Same collision openSearch
        // and onArtistLoaded already guard against.
        scoped: !!(artistData && artistData.libraryScoped),
        scrollY: artistView.contentY,
        ex: expandedAlbums,
        bio: bioExpanded
      }
    if (browseOpen)
      return {
        v: "browse",
        key: browsePageKey,
        page: browsePage,
        stack: browseStack.slice(),
        hi: browseHighlightId,
        scrollY: browsePageKey === "" ? browseLanding.contentY : browseDrill.contentY,
        label: browsePageKey === "" ? "Browse" : browsePage ? (browsePage.title || "Browse") : (browseTitleHint !== "" ? browseTitleHint : "Browse"),
        art: browsePageKey !== "" && !browsePage ? browseArtHint : ""
      }
    return {
      v: "search",
      label: "Search"
    }
  }
  function navPush() {
    if (_navRestoring)
      return
    _navRestored = false
    // a genuine navigation: the trim guard must not carry over
    navForwardHistory = []
    // a genuine new navigation invalidates any redo history
    var s = navSnapshot()
    s.o = navOrigin
    // restore the lit tab along with the view
    if (navHistory.length > 0 && navSig(navHistory[navHistory.length - 1]) === navSig(s))
      return
    navHistory = navHistory.concat([s]).slice(-50)
  }
  function navBackLabel() {
    return navHistory.length > 0 ? navHistory[navHistory.length - 1].label : ""
  }
  function navBack() {
    var levelUp = navHistory.length === 0;
    // A Back press that lands nowhere (nothing recorded, no surface open:
    // the search root) must stay a complete no-op. Marking it would bump
    // _navSeq and make an in-flight search's results get discarded, and
    // recording a forward entry would cost one dead Forward press per
    // over-press. navForward() already returns before its markNav.
    if (levelUp && !settingsOpen && !libraryOpen && !artistOpen && !browseOpen)
      return
    markNav("back")
    saveSearchView()
    // leaving Search via Back must also keep its drill-in restorable
    var fwd = navSnapshot()
    fwd.o = navOrigin
    navForwardHistory = navForwardHistory.concat([fwd]).slice(-50)
    if (levelUp) {
      // Nothing recorded (fresh session view): fall back to closing the
      // open surface.
      if (setupOpen)
        setupOpen = false
      else if (settingsOpen)
        settingsOpen = false
      else if (libraryOpen)
        libraryOpen = false
      else if (artistOpen)
        artistOpen = false
      else if (browseOpen && browsePageKey !== "")
        browseBack()
      else if (browseOpen)
        browseOpen = false
      navOrigin = libraryOpen ? "library" : browseOpen ? "browse" : settingsOpen ? navOrigin : "search"
      return
    }
    var s = navHistory[navHistory.length - 1]
    navHistory = navHistory.slice(0, navHistory.length - 1)
    _navRestore(s)
  }
  function navForward() {
    if (navForwardHistory.length === 0)
      return
    markNav("forward")
    saveSearchView()
    // leaving Search via Forward must also keep its drill-in restorable
    var s = navSnapshot()
    s.o = navOrigin
    navHistory = navHistory.concat([s]).slice(-50)
    var t = navForwardHistory[navForwardHistory.length - 1]
    navForwardHistory = navForwardHistory.slice(0, navForwardHistory.length - 1)
    _navRestore(t)
  }
  function _navRestore(s) {
    // Restore the snapshot's lit tab; older snapshots without one fall back
    // to the section the snapshot itself shows.
    navOrigin = s.o || (s.v === "library" ? "library" : s.v === "browse" ? "browse" : s.v === "search" ? "search" : navOrigin)
    _navRestoring = true
    if (s.v === "settings") {
      setupOpen = false
      settingsOpen = true
      artistOpen = false
      libraryOpen = false
    } else if (s.v === "library") {
      libraryOpen = true
      settingsOpen = false
      setupOpen = false
      artistOpen = false
      if (libraryCategory !== s.cat)
        loadLib(s.cat)
    } else if (s.v === "artist") {
      if (artistData && ("" + artistData.id) === s.id && !!artistData.libraryScoped === !!s.scoped) {
        artistOpen = true
        settingsOpen = false
        setupOpen = false
        libraryOpen = false
        // The page's content is still loaded; put back the state other
        // tabs may have clobbered (loadLib clears expandedAlbums), and
        // land on the saved spot same-frame, pre-paint (the pane only
        // becomes visible this frame, same rule as openSearch).
        resetExpandedAlbums(s.ex)
        bioExpanded = !!s.bio
        // Section expansion is a persisted per-section pref now (like
        // the search sections), so snapshots neither carry nor restore
        // it: the pref would just be overwritten with stale state.
        if (s.scrollY !== undefined)
          artistView.contentY = Math.min(s.scrollY, Math.max(0, artistView.contentHeight - artistView.height))
      } else if (s.id) {
        // The artist must be re-loaded (usually a warm backend cache).
        // Arm the pre-paint scroll restore, tagged with the artist id,
        // and stash the expansion state for onArtistLoaded to re-apply.
        artistView.pendingRestoreKey = s.id
        artistView.pendingRestoreY = (s.scrollY !== undefined ? s.scrollY : -1)
        _artistRestoreState = {
          id: s.id,
          ex: s.ex,
          bio: s.bio
        }
        // Back to the page that was actually saved: the two share an
        // id and a signal, so loading the wrong one puts the other
        // artist page up under this one's history entry.
        if (s.scoped)
          waves.loadArtistLibrary(s.id)
        else
          waves.loadArtist(s.id)
        // flag cleared in onArtistLoaded
        return
      }
    } else if (s.v === "browse") {
      browseOpen = true
      settingsOpen = false
      setupOpen = false
      artistOpen = false
      libraryOpen = false
      browseStack = s.stack || []
      browseHighlightId = s.hi || ""
      var bkey = s.key || ""
      if (bkey === "") {
        // The landing pane is alive and still positioned; showing it
        // is the whole restore. Its own contentY is the truth (a
        // revalidate may have reshaped the page since the snapshot),
        // so the recorded scrollY is deliberately not re-applied.
        // browsePage deliberately stays set: the drill pane stays
        // alive behind the landing, so Forward (or reopening the
        // same page) costs nothing and Back pays no teardown.
        browsePageKey = ""
        browseTitleHint = ""
        browseArtHint = ""
        browsePageLoading = false
        browsePageError = false
      } else if (bkey === browsePageKey && browsePage) {
        // The drilled page snapshotted is the one still loaded in
        // the drill pane (a round trip through another section):
        // alive, positioned, possibly fresher than the snapshot.
        // Reassigning browsePage here would rebuild it for nothing.
      } else {
        // A different drilled page: this is a real rebuild, so arm
        // the scroll restore BEFORE changing the page key. It's
        // tagged with the destination key so the pane applies it
        // (rather than jumping to the top) once that page is
        // showing, pre-paint, and Back lands where you left off.
        browseDrill.pendingRestoreKey = bkey
        browseDrill.pendingRestoreY = (s.scrollY !== undefined ? s.scrollY : -1)
        browsePageKey = bkey
        browsePage = s.page || null
        // A page snapshotted mid-load has no payload; its label and
        // cover are the best (and only) face for it until the user
        // reloads it: the header shows them as a skeleton, nothing is
        // fetched (same as the blank pane before, with a face on it).
        browseTitleHint = !s.page ? (s.label || "") : ""
        browseArtHint = !s.page ? (s.art || "") : ""
        browsePageLoading = false
        browsePageError = false
      }
      if (root.signedIn && browseSections.length === 0 && !browseLoading) {
        browseLoading = true
        browseError = false
        waves.loadBrowse()
      } else if (root.signedIn) {
        waves.refreshBrowse()
        // silent, throttled; repaints only on change
      }
    } else {   // search
      settingsOpen = false
      setupOpen = false
      artistOpen = false
      libraryOpen = false
      browseOpen = false
    }
    _navRestoring = false
    _navRestored = true
    // survives the 0ms crumb-trim debounce (see crumbTrimTimer)
  }
  // Breadcrumb trail over the history
  // The artist and browse sub-page back bars render the whole navHistory as
  // a crumb trail (NavCrumbTrail) with the current page as the last, lit
  // pill. These mirror navSnapshot()'s label and navSig() WITHOUT reading
  // scroll positions, so the bindings don't re-evaluate on every scrolled
  // frame.
  // A keyed browse page still loading with no title hint yields "": the
  // trail holds the crumb back rather than flash "Browse" and then swap in
  // the real name when the payload arrives.
  readonly property string currentNavLabel: settingsOpen ? "Settings" : libraryOpen ? "My Music" : artistOpen ? (artistData ? (artistData.name || "Artist") : "Artist") : browseOpen ? (browsePageKey === "" ? "Browse" : browsePage ? (browsePage.title || "Browse") : browseTitleHint) : "Search"
  // The page is open but cannot be named yet (opened without a title hint,
  // payload not in). The trail holds its crumb back rather than flash
  // "Browse", which leaves the PARENT as the last pill: without this, the
  // parent would be lit as though it were the page you are on, and its click
  // disabled for the same reason, so the one crumb that could get you back
  // stops working. Reached from the now-playing title and the video player,
  // which know an album id but no album name, and it lasts until the payload
  // arrives (indefinitely, if the load errors).
  readonly property bool crumbTailPending: currentNavLabel === ""
  function currentNavSig() {
    var v = settingsOpen ? "settings" : libraryOpen ? "library" : artistOpen ? "artist" : browseOpen ? "browse" : "search"
    return v + "|" + (v === "browse" ? browsePageKey : "") + "|" + (v === "artist" ? (artistData ? "" + artistData.id : "") : "") + "|" + (v === "library" ? libraryCategory : "")
  }
  // SECTION-SCOPED TRAIL. The trail shows the drill-in you are actually
  // inside, never the tabs you passed through to get here: switching tab
  // starts a fresh trail, drilling deeper extends it. Every snapshot records
  // the section it was taken in (s.o, the lit tab), so the trail is the run
  // of entries at the tail of the history whose section is the current one;
  // the first entry from another section ends it. Back and Forward keep
  // working ACROSS sections (they walk the whole navHistory), they just stop
  // spelling the crossing out in crumbs.
  // This is also what bounds the trail: its depth is how deep you drilled,
  // not how much you browsed. Tab-flipping cannot stack it.
  readonly property int crumbBase: {
    var k = navHistory.length
    while (k > 0 && (navHistory[k - 1].o || "") === navOrigin)
      k--
    return k
  }
  // SYNTHETIC SECTION-ROOT CRUMB. A drilled page can be the whole trail:
  // returning to a section via its nav tab lands on the page it was left on
  // (keep-alive), but the tab switch also starts a fresh section-scoped
  // trail, so the crumb row would hold a single, unclickable pill and the
  // only way up is the tab button or the Back gesture. Whenever the
  // trail of a drilled page does not begin at a section root, a synthetic
  // root pill ("Browse", "Search", "My Music") leads it, and clicking it
  // climbs out of the drill within the section (the keep-alive panes make
  // that a pure flip). It is display-only: history is untouched until it
  // is clicked, which records the drilled page like any navigation.
  readonly property bool crumbSynth: {
    var drilled = artistOpen || (browseOpen && !settingsOpen && !libraryOpen && browsePageKey !== "")
    if (!drilled || settingsOpen)
      return false
    if (crumbBase >= navHistory.length)
      return true
    return !navIsRoot(navHistory[crumbBase])
  }
  readonly property string crumbSynthLabel: navOrigin === "library" ? "My Music" : navOrigin === "browse" ? "Browse" : "Search"
  function crumbSynthGo() {
    navPush()
    markNav("crumb root")
    if (navOrigin === "browse") {
      // Up to the Browse landing: the drilled page idles behind it
      // (keep-alive), its lineage is done (same as the tab's home
      // strike), but the landing keeps its own scroll.
      browseStack = []
      browseHighlightId = ""
      browseTitleHint = ""
      browseArtHint = ""
      browsePageLoading = false
      browsePageError = false
      browsePageKey = ""
      artistOpen = false
      settingsOpen = false
      setupOpen = false
      libraryOpen = false
      browseOpen = true
    } else if (navOrigin === "library") {
      artistOpen = false
      settingsOpen = false
      setupOpen = false
      browseOpen = false
      libraryOpen = true
    } else {
      // Search: uncover the results pane exactly as it stands.
      artistOpen = false
      settingsOpen = false
      setupOpen = false
      libraryOpen = false
      browseOpen = false
    }
  }
  readonly property var crumbLabels: {
    var out = []
    if (crumbSynth)
      out.push(crumbSynthLabel)
    for (var i = crumbBase; i < navHistory.length; i++)
      out.push(navHistory[i].label || "")
    if (currentNavLabel !== "")
      out.push(currentNavLabel)
    // "" = name not known yet
    return out
  }
  // TRIM-ON-REVISIT: arriving at a SECTION ROOT (Search, My Music, Browse
  // home, Settings) that is already in the history cuts the history back
  // to just before it, so flipping between two tabs bounces between two
  // crumbs instead of stacking Search > My Music > Search > ... twenty
  // deep (and Back stops replaying the oscillation). Deep pages (artist,
  // browse sub-pages) are deliberately NOT trimmed: reopening a playlist
  // page from inside a folder must keep the folder in the history or Back
  // would skip it.
  // Debounced through a 0ms timer so it runs once the navigation functions
  // have finished flipping flags, never against a half-switched state.
  // _navRestoring is already back to false by the time the 0ms timer fires,
  // so that guard alone never fired: a Back or Forward landing on a section
  // root would trim away the very history it had just walked into, and the
  // next Back press fell through to the level-up fallback. Latch the restore
  // across the debounce instead (cleared by the timer, and by navPush so a
  // genuine navigation can never inherit it).
  property bool _navRestored: false
  onCrumbLabelsChanged: crumbTrimTimer.restart()
  Timer {
    id: crumbTrimTimer
    interval: 0
    onTriggered: {
      var restored = root._navRestored
      root._navRestored = false
      if (!restored)
        root.crumbTrimRevisit()
    }
  }
  // A section root: a tab's own landing, nothing drilled into. Only these
  // are disposable (see crumbTrimRevisit).
  function navIsRoot(s) {
    return s.v === "search" || s.v === "library" || s.v === "settings" || (s.v === "browse" && (s.key || "") === "")
  }
  function crumbTrimRevisit() {
    if (_navRestoring)
      return
    if (artistOpen || (browseOpen && browsePageKey !== ""))
      return
    var sig = currentNavSig()
    for (var k = 0; k < navHistory.length; k++) {
      if (navSig(navHistory[k]) !== sig)
        continue
      // Everything from here on is about to be discarded, so it may only
      // be the oscillation itself. A real page in the way (an artist, a
      // browse sub-page) means this is not a tab flip but a journey, and
      // dropping it would make Back skip a page the user actually opened:
      // Browse > artist > Search tab > Browse tab would lose the artist
      // from Back entirely. Leave the history alone; the trail stays
      // short on its own, because it only shows this section (crumbBase).
      for (var j = k; j < navHistory.length; j++)
        if (!navIsRoot(navHistory[j]))
          return
      navHistory = navHistory.slice(0, k)
      return
    }
  }
  // Crumb click: jump straight back to history entry i. Dropping everything
  // after it and letting navBack pop-and-restore entry i itself reuses the
  // whole restore path (scroll spot, expanded albums, pre-paint landing).
  function navTo(i) {
    if (i < 0 || i >= navHistory.length)
      return
    navHistory = navHistory.slice(0, i + 1)
    navBack()
  }
  // Set the target view true BEFORE clearing the others: the Search tab's
  // `active` is `!artistOpen && !libraryOpen && !settingsOpen`, so clearing the
  // old view first would transiently make Search active and fire its power-on
  // animation mid-switch. Target-first keeps Search inactive throughout.
  function openLibrary() {
    saveSearchView()
    // Second press, My Music already active: land on Home, mirroring the
    // Browse tab's second press landing on its main page.
    var alreadyActive = libraryOpen && !artistOpen && !settingsOpen && navOrigin === "library"
    if (alreadyActive) {
      navPush()
      markNav("library home")
      loadLib("home")
      return
    }
    navPush()
    markNav("library")
    navOrigin = "library"
    libraryOpen = true
    settingsOpen = false
    setupOpen = false
    artistOpen = false
    // The Library section loads with the pane (Saved is its default
    // view): it is provider-independent, so no source group loads it.
    libSection.ensureLoaded()
    // RETURN to the category the user left, not always Home. loadLib is
    // keep-alive: a category whose rows are already on screen keeps them
    // (and its scroll) untouched and only revalidates quietly.
    loadLib(libraryCategory)
  }

  // Search tab state save/restore
  // The artist drill-in state (artistData/expandedAlbums) is SHARED between
  // tabs, and other tabs overwrite it (My Music opens its own artist pages,
  // loadLib clears expandedAlbums). So the Search tab's exact view is
  // snapshotted the moment the user leaves the tab, and the Search nav
  // button restores it: first press returns exactly where you were (artist
  // page, expanded album, scroll); a second press while already on Search
  // resets to a blank search page, mirroring Browse's two-step behaviour.
  property var searchSaved: null
  function saveSearchView() {
    if (navOrigin !== "search" || settingsOpen)
      return
    searchSaved = (artistOpen && artistData && artistData.id) ? {
      artistData: artistData,
      expandedAlbums: expandedAlbums,
      bio: bioExpanded,
      artistY: artistView.contentY,
      resultsY: results.contentY
    } : {
      resultsY: results.contentY
    }
  }
  function openSearch() {
    // The setup surface counts as another page even when it was opened
    // from Search (the empty-state sign-in CTA): leaving it is one nav
    // click, and the Search tab uncovers the view it was opened from
    // instead of blanking the search behind the still-open surface.
    var onSearchTab = navOrigin === "search" && !settingsOpen && !libraryOpen && !browseOpen && !setupOpen
    if (!onSearchTab) {
      navPush()
      markNav("search restore")
      var fromOtherTab = navOrigin !== "search"
      navOrigin = "search"
      if (fromOtherTab) {
        // Restore the saved drill-in BEFORE clearing the tab flags so
        // the results pane never flashes underneath (same target-first
        // rule as openLibrary).
        var s = searchSaved
        if (s && s.artistData && s.artistData.id) {
          // The four section models are SHARED with every other
          // tab's artist page, so another tab may have refilled them
          // with a different artist since the snapshot was taken.
          // Only the header reads artistData; putting it back on its
          // own gave one artist's name, photo and DOWNLOAD
          // DISCOGRAPHY button over another artist's albums and top
          // tracks. The payload the page was built from IS the
          // snapshot, so the sections are refilled from it: no
          // refetch, and nothing to go wrong offline.
          // The id alone does not identify a page. My Music opens a
          // LIBRARY-SCOPED page of the same artist (loadArtistLibrary,
          // same id, same signal) whose payload carries only the
          // favourited albums, EPs and tracks and no videos at all,
          // and it fills these same four models. Matching ids there
          // meant the refill was skipped and the full page's header
          // and DOWNLOAD DISCOGRAPHY button stood over the
          // favourites subset, so the scope has to agree too. It is
          // the same-id collision the refresh path already guards
          // against in onArtistLoaded.
          var pageLoaded = artistData && ("" + artistData.id) === ("" + s.artistData.id) && !!artistData.libraryScoped === !!s.artistData.libraryScoped
          artistData = s.artistData
          if (!pageLoaded) {
            fillMedia(artistAlbumsModel, s.artistData.albums || [])
            fillMedia(artistEpModel, s.artistData.eps || [])
            fillMedia(artistTracksModel, s.artistData.tracks || [])
            fillMedia(artistVideosModel, s.artistData.videos || [])
          }
          resetExpandedAlbums(s.expandedAlbums)
          bioExpanded = !!s.bio
          artistOpen = true
          browseOpen = false
          libraryOpen = false
          settingsOpen = false
          setupOpen = false
          // Same-frame restore: the pane becomes visible this frame,
          // so clamping contentY now lands pre-paint (no visible jump).
          artistView.contentY = Math.min(s.artistY || 0, Math.max(0, artistView.contentHeight - artistView.height))
        } else {
          artistOpen = false
          browseOpen = false
          libraryOpen = false
          settingsOpen = false
          setupOpen = false
          if (s)
            results.contentY = Math.min(s.resultsY || 0, Math.max(0, results.contentHeight - results.height))
        }
      } else {
        // Only Settings was covering the Search view: uncover it as-is.
        settingsOpen = false
        setupOpen = false
        browseOpen = false
        libraryOpen = false
      }
      // Ready to type immediately: the Search press hands the keyboard
      // to the field (existing text selected, so typing replaces it).
      searchField.forceActiveFocus()
      searchField.selectAll()
      return
    }
    // Second press while already on Search: a fresh, blank search page.
    navPush()
    markNav("search blank")
    artistOpen = false
    searchSaved = null
    searchField.text = ""
    trackCache = ({})
    resetExpandedAlbums({})
    playlistTrackCache = ({})
    expandedPlaylists = ({})
    _searchBuildStart(0)
    // a mid-build blank must drop the veil with the cards
    // Every provider's group goes with the blank page: the rows, the
    // folds, the errors and the pinned tops all live on those instances.
    searchGroups = []
    searchField.forceActiveFocus()
  }
  // The pane's shelves are the source groups': opening My Music
  // selects the category on the primary source and lets every other source
  // load its own current shelf, so a second provider's group is not a blank
  // pane the user has to click. Nothing to load with no source: the pane's
  // empty state is on screen instead.
  function loadLib(cat) {
    var groups = root.libGroupList()
    if (groups.length === 0)
      return
    groups[0].select(cat)
    for (var i = 1; i < groups.length; ++i)
      groups[i].select(groups[i].category)
  }
  // Deep-link to the download-folder setting (from the folder gate/nudge), the
  // same instant jump the update notice uses, no scroll animation.
  function openDownloadSetting() {
    navPush()
    markNav("settings")
    setupOpen = false
    settingsOpen = true
    artistOpen = false
    libraryOpen = false
    browseOpen = false
    Qt.callLater(function () {
      settingsPage.jumpToCard("downloads")
    })
  }
  // Deep-link to the FFmpeg card (from the pre-download gate).
  function openFfmpegSetting() {
    navPush()
    markNav("settings")
    setupOpen = false
    settingsOpen = true
    artistOpen = false
    libraryOpen = false
    browseOpen = false
    Qt.callLater(function () {
      settingsPage.jumpToCard("ffmpeg")
    })
  }
  // Deep-link to the Music library card (from the Library section's
  // configure CTA): the one place that owns the scanned folder.
  function openLibrarySetting() {
    navPush()
    markNav("settings")
    setupOpen = false
    settingsOpen = true
    artistOpen = false
    libraryOpen = false
    browseOpen = false
    Qt.callLater(function () {
      settingsPage.jumpToCard("library")
    })
  }
  // The chip's ✕ and its test both come through here.
  function dismissSetupChip() {
    setupSettings.setupChipDismissed = true
  }
  // The welcome surface was answered: persist the answer, route the choice,
  // and close the surface. TIDAL swaps the SAME surface to its inline
  // sign-in steps and stays up: the first run is not answered until the
  // sign-in succeeds, so a cancel leaves nothing behind.
  // Apple enables and the existing wizard routing takes over; Skip just
  // lands in the app.
  function answerWelcome(choice) {
    if (choice === "tidal") {
      setupMode = "tidal"
      setupUrlOpened = false
      return
    }
    setupSettings.firstRunAnswered = true
    setupOpen = false
    setupCards()
    if (choice === "apple") {
      // Choosing the card means set it up, whether Apple was already on
      // (a re-opened welcome page after Skip) or not: the enable's own
      // wizard request only fires on a real flip, so an already-enabled
      // Apple would otherwise close the surface and open nothing.
      var wasEnabled = root.appleEnabled
      waves.applySettings({
        "apple_enabled": true
      })
      if (wasEnabled)
        root.openAppleSetup("")
    }
  }
  // One reset for every path that leaves the TIDAL steps: the mode and the
  // paste-field latch fall back together, so no exit can leave a late URL
  // opening a browser or a stale "REOPEN" step behind.
  function setupCards() {
    setupMode = "cards"
    setupUrlOpened = false
  }
  // Cancel/Escape from the TIDAL sign-in steps: back to the provider cards.
  // The abandoned browser flow is not retried or reported, and the surface
  // stays exactly where it was (the first-run gate or the welcome page).
  function cancelSetupSignIn() {
    setupCards()
  }
  // The TIDAL sign-in entry points (Settings -> Providers, the Search and
  // Browse empty states, My Music's empty state) open the welcome page on
  // the same inline steps. No browser opens here: the steps' own button is
  // the only caller of beginLogin.
  function openSetupSignIn() {
    root.openProviderSignIn("tidal")
  }
  // A completed sign-in answers the first run, closes the welcome/sign-in
  // surface and lands on Search with its field focused.
  function finishSetupSignIn() {
    // No early return on a cancelled mode: a login that lands after the
    // user left the steps still closes the surface and answers the first
    // run, or a completed sign-in would strand the welcome page.
    setupCards()
    setupOpen = false
    setupSettings.firstRunAnswered = true
    openSearch()
  }
  // Re-open the welcome surface as a page (Settings -> Providers, or the
  // "Finish setup" chip): the other surfaces close, the page opens on the
  // provider cards whatever the last session left behind, with their live
  // statuses re-read for this visit.
  function openSetupPage() {
    navPush()
    markNav("setup")
    settingsOpen = false
    artistOpen = false
    libraryOpen = false
    browseOpen = false
    setupCards()
    root.refreshProviderSurfaces()
    setupOpen = true
  }
  // Deep-link to the Apple setup wizard (from enabling Apple Music or a
  // pre-setup Apple download click): the in-place steps in Providers. The
  // reason names the step the click was missing (a wizard step key) or
  // "" / "setup" for the top of the wizard, so the click lands on the
  // affordance that would have let it work.
  function openAppleSetup(reason) {
    navPush()
    markNav("settings")
    setupOpen = false
    settingsOpen = true
    artistOpen = false
    libraryOpen = false
    browseOpen = false
    var step = String(reason || "")
    settingsPage.appleFocusStep = (step === "setup") ? "" : step
    Qt.callLater(function () {
      settingsPage.jumpToCard("providers_apple")
    })
  }
  // Browse: open the tab (fetching the landing page once per session) and
  // drill into an editorial page. Target-first flag order, same as above.
  function openBrowse() {
    // No configured provider fills Browse: the tab is
    // hidden, and a programmatic open (a deep link, the login
    // hand-off) falls through to Search instead of a dead pane.
    if (!root.browseAvailable) {
      openSearch()
      return
    }
    // Coming from another section, the tab RETURNS to Browse exactly as it
    // was left (open sub-page, stack, scroll all intact). Only a second
    // click, Browse already active and highlighted, goes home.
    saveSearchView()
    var alreadyActive = browseOpen && !artistOpen && !libraryOpen && !settingsOpen && navOrigin === "browse"
    if (!alreadyActive) {
      navPush()
      markNav("browse return")
      navOrigin = "browse"
      browseOpen = true
      settingsOpen = false
      setupOpen = false
      artistOpen = false
      libraryOpen = false
      if (root.signedIn && browseSections.length === 0 && !browseLoading) {
        browseLoading = true
        browseError = false
        waves.loadBrowse()
      } else if (root.signedIn) {
        waves.refreshBrowse()
        // silent, throttled; repaints only on change
      }
      return
    }
    navPush()
    markNav("browse")
    // The tab button always lands on the main Browse page: drop any open
    // sub-page (genre / playlist / album) and its stack. The landing
    // pane is alive; this only flips it visible.
    browseStack = []
    browsePageKey = ""
    browseTitleHint = ""
    // the landing is "Browse", never the page we left
    browseArtHint = ""
    browsePageLoading = false
    browsePageError = false
    browseHighlightId = ""
    browseOpen = true
    settingsOpen = false
    setupOpen = false
    artistOpen = false
    libraryOpen = false
    // The tab button is an explicit "take me to the top of Browse":
    // cancel any armed hold and reset the landing's scroll directly
    // (the pane is alive, so a plain set is exact).
    browseLanding.pendingRestoreY = -1
    browseLanding.contentY = 0
    if (root.signedIn && browseSections.length === 0 && !browseLoading) {
      browseLoading = true
      browseError = false
      waves.loadBrowse()
    } else if (root.signedIn) {
      waves.refreshBrowse()
      // silent, throttled; repaints only on change
    }
  }
  function openBrowseLink(path, title) {
    navPush()
    // browsePage stays set while the landing shows (the drill pane
    // is kept alive for an instant return), so "there is a page" is
    // browsePageKey, not browsePage: pushing the stale object here
    // would make Back detour through a page the user already left.
    if (browsePageKey !== "" && browsePage)
      browseStack = browseStack.concat([browsePage])
    browseHighlightId = ""
    browsePageKey = path
    browsePage = null
    browseTitleHint = title || ""
    // names the crumb until the payload lands
    browseArtHint = ""
    // editorial pages have no hero
    browsePageError = false
    browsePageLoading = true
    waves.openBrowsePage(path, title)
  }
  // Re-issue the current drilled page's fetch after an error. The key alone
  // says which backend entry built the page: openBrowsePage only answers
  // pages/… paths, so routing a pl:… (filtered playlists grid) or item:…
  // (playlist/mix/album page) key through it makes no request at all and
  // the loading hint never clears. No navPush: a retry is not a navigation.
  function retryBrowsePage() {
    var key = "" + browsePageKey
    browsePageError = false
    browsePageLoading = true
    if (key.indexOf("pl:") === 0) {
      waves.openBrowsePlaylists(key.substring(3), browseTitleHint)
    } else if (key.indexOf("item:") === 0) {
      var rest = key.substring(5)
      var cut = rest.indexOf(":")
      waves.openBrowseItem(rest.substring(0, cut), rest.substring(cut + 1))
    } else {
      waves.openBrowsePage(key, browseTitleHint)
    }
  }
  // Some rows (Custom mixes, Radio stations, New releases…) have no TIDAL
  // "show more" path. Their headline still opens a full listing: a local
  // page synthesized from the row's own items, rendered by the same grid
  // page as fetched listings, no network fetch, instant, Back just works
  // because the page object is a plain snapshot like any loaded page.
  function openBrowseSection(sec) {
    var key = "local:" + (sec.title || "More")
    if (browsePageKey === key)
      // already there
      return
    navPush()
    // browsePage stays set while the landing shows (the drill pane
    // is kept alive for an instant return), so "there is a page" is
    // browsePageKey, not browsePage: pushing the stale object here
    // would make Back detour through a page the user already left.
    if (browsePageKey !== "" && browsePage)
      browseStack = browseStack.concat([browsePage])
    browseHighlightId = ""
    browsePageKey = key
    browsePageError = false
    browsePageLoading = false
    browsePage = {
      key: key,
      title: sec.title || "More",
      sections: [
        {
          rowKind: sec.rowKind,
          title: sec.title || "More",
          items: sec.items || [],
          more: "",
          // carry the paging handle so a local
          // listing endless-scrolls like fetched ones
          data: sec.data || "",
          total: sec.total || 0,
          offset: sec.offset || 0,
          modType: sec.modType || ""
        }
      ]
    }
  }
  // A local: page is a snapshot of its landing row taken at click time; a
  // background revalidation can deliver a fresher ordering afterwards (e.g.
  // "New tracks" gaining releases at the top). Re-snapshot from the fresh
  // row when its head no longer matches; a page whose head still agrees is
  // left alone, preserving any endless-scroll growth and the user's place.
  function localPageFresh(pg, rows) {
    if (!pg || ("" + pg.key).indexOf("local:") !== 0)
      return null
    if (!pg.sections || pg.sections.length === 0)
      return null
    var cur = pg.sections[0]
    function ids(list, n) {
      var out = []
      for (var k = 0; k < list.length && (n < 0 || k < n); k++)
        out.push("" + list[k].kind + ":" + list[k].id)
      return out.join("\n")
    }
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i]
      var match = cur.data ? r.data === cur.data : (r.rowKind === cur.rowKind && r.title === cur.title)
      if (!match)
        continue
      var head = r.items || []
      if (ids(head, -1) === ids(cur.items || [], head.length))
        return null
      // unchanged
      return {
        key: pg.key,
        title: pg.title,
        sections: [
          {
            rowKind: r.rowKind,
            title: r.title || pg.title,
            items: head,
            more: "",
            data: r.data || "",
            total: r.total || 0,
            offset: r.offset || 0,
            modType: r.modType || ""
          }
        ]
      }
    }
    return null
  }
  function refreshLocalBrowsePages(rows) {
    var fresh = localPageFresh(browsePage, rows)
    if (fresh)
      browsePage = fresh
    var changed = false
    var st = browseStack.map(function (pg) {
      var f = localPageFresh(pg, rows)
      if (f)
        changed = true
      return f || pg
    })
    if (changed)
      browseStack = st
  }
  // Open all of one wayfinding cloud (Genres / Moods / Decades) as its own
  // page: the landing shows these as horizontal tile shelves, and their
  // headline drills into a wrapping grid of the same tiles (a "links"
  // section, see the Flow in the browse delegate). Local, no fetch: the
  // clouds already hold every tile TIDAL's "show more" would return.
  // Browse's folder-style Playlists view. Level 1 (openPlaylistsRoot) is a
  // local page of the wayfinding clouds re-cast as playlist folders (moods
  // first, they are the most playlist-dense); level 2 (openPlaylistsFolder)
  // fetches that category's page filtered to just its playlists. Items
  // carry pl: true so the shared links/tile delegates route back here
  // instead of to the unfiltered page.
  function plChips(chips) {
    return (chips || []).map(function (c) {
      return {
        title: c.title,
        path: c.path,
        pl: true
      }
    })
  }
  function openPlaylistsFolder(path, title) {
    var key = "pl:" + path
    if (browsePageKey === key)
      return
    navPush()
    // browsePage stays set while the landing shows (the drill pane
    // is kept alive for an instant return), so "there is a page" is
    // browsePageKey, not browsePage: pushing the stale object here
    // would make Back detour through a page the user already left.
    if (browsePageKey !== "" && browsePage)
      browseStack = browseStack.concat([browsePage])
    browseHighlightId = ""
    browsePageKey = key
    browsePage = null
    browseTitleHint = title || ""
    // names the crumb until the payload lands
    browseArtHint = ""
    // a playlist grid has no hero
    browsePageError = false
    browsePageLoading = true
    waves.openBrowsePlaylists(path, title)
  }
  function openPlaylistsRoot() {
    var key = "cloud:All Playlists"
    if (browsePageKey === key)
      return
    navPush()
    // browsePage stays set while the landing shows (the drill pane
    // is kept alive for an instant return), so "there is a page" is
    // browsePageKey, not browsePage: pushing the stale object here
    // would make Back detour through a page the user already left.
    if (browsePageKey !== "" && browsePage)
      browseStack = browseStack.concat([browsePage])
    browseHighlightId = ""
    browsePageKey = key
    browsePageError = false
    browsePageLoading = false
    browsePage = {
      key: key,
      title: "All Playlists",
      sections: [
        {
          rowKind: "links",
          title: "Moods & Activities",
          items: plChips(browseChips.moods)
        },
        {
          rowKind: "links",
          title: "Genres",
          items: plChips(browseChips.genres)
        },
        {
          rowKind: "links",
          title: "Decades",
          items: plChips(browseChips.decades)
        }
      ]
    }
  }
  function openBrowseCloud(title, chips) {
    var key = "cloud:" + title
    if (browsePageKey === key)
      return
    navPush()
    // browsePage stays set while the landing shows (the drill pane
    // is kept alive for an instant return), so "there is a page" is
    // browsePageKey, not browsePage: pushing the stale object here
    // would make Back detour through a page the user already left.
    if (browsePageKey !== "" && browsePage)
      browseStack = browseStack.concat([browsePage])
    browseHighlightId = ""
    browsePageKey = key
    browsePageError = false
    browsePageLoading = false
    browsePage = {
      key: key,
      title: title,
      sections: [
        {
          rowKind: "links",
          title: title,
          items: chips || []
        }
      ]
    }
  }
  // Shared grid geometry so every drilled box view (album/mix/playlist cards
  // AND genre/mood/label tiles) centers and re-columns identically: how many
  // fixed-width cards fit across `avail`, capped at the item count so a short
  // row centers its items instead of hugging the left.
  function gridCols(cardW, spacing, count, avail) {
    var fit = Math.max(1, Math.floor((avail + spacing) / (cardW + spacing)))
    return Math.max(1, Math.min(fit, count))
  }
  // browse endless scroll
  // A row that carries a paging handle (data/total/offset) can grow: shelves
  // ask when scrolled to their end, drilled pages when the view hits bottom.
  // One in-flight fetch per data path; results splice into whichever views
  // hold the row at that offset (backend keeps its caches in step).
  property var browseGrowing: ({})
  function browseCanGrow(sec) {
    return !!(sec && sec.data) && (sec.offset || 0) < (sec.total || 0)
  }
  function browseGrow(sec) {
    if (!browseCanGrow(sec) || browseGrowing[sec.data])
      return
    var g = Object.assign({}, browseGrowing)
    g[sec.data] = true
    browseGrowing = g
    waves.loadBrowseSectionMore(browsePageKey, sec.data, sec.offset || 0, sec.modType || "", sec.title || "")
  }
  function browseGrew(p) {
    var g = Object.assign({}, browseGrowing)
    delete g[p.data]
    browseGrowing = g
    if (p.error || (p.items || []).length === 0)
      return
    browseArtistsSideMap([p])
    function grown(rows) {
      var hit = false
      var out = (rows || []).map(function (r) {
        if (r.data !== p.data || (r.offset || 0) !== p.reqOffset)
          return r
        hit = true
        return Object.assign({}, r, {
          items: (r.items || []).concat(p.items),
          offset: p.offset,
          total: p.more ? r.total : p.offset
        })
      })
      return hit ? out : null
    }
    _browseAsyncBuild = false
    // growth re-lays the landing in place, never streamed
    var s = grown(browseSections)
    var ps = (browsePage && browsePage.sections) ? grown(browsePage.sections) : null
    // Growth rebuilds a column in place; hold the user's spot across it,
    // on whichever pane actually re-lays.
    if (s)
      browseLanding.holdScroll()
    if (ps)
      browseDrill.holdScroll()
    if (s)
      browseSections = s
    if (ps)
      browsePage = Object.assign({}, browsePage, {
        sections: ps
      })
  }
  // Open one playlist / mix / album as its own page inside Browse (art
  // header + track list). Drilling from an editorial page pushes it onto
  // browseStack so Back walks up one level at a time.
  // `art` is the opener's own cover URL (a card's, a row's): the hero
  // paints it at once, before the payload, see browseArtHint.
  function openBrowseItem(kind, id, highlight, title, art) {
    if (browsePageKey === "item:" + kind + ":" + id) {
      // Already keyed to this page, nothing to fetch. But the key
      // survives leaving Browse via the nav tabs, so "already there"
      // is only true when Browse is the active surface. Arriving from
      // another surface (a folder row, a My Music shelf) must still
      // record where the user came from: returning without pushing
      // would make Back skip the folder entirely and fall through to
      // whatever is under it in the history (Search).
      if (!browseOpen || artistOpen || settingsOpen || libraryOpen)
        navPush()
      browseHighlightId = highlight || ""
      browseHighlightPending = false
      return
    }
    navPush()
    // browsePage stays set while the landing shows (the drill pane
    // is kept alive for an instant return), so "there is a page" is
    // browsePageKey, not browsePage: pushing the stale object here
    // would make Back detour through a page the user already left.
    if (browsePageKey !== "" && browsePage)
      browseStack = browseStack.concat([browsePage])
    browseHighlightId = highlight || ""
    browseHighlightPending = false
    // the highlighted row re-arms this on layout
    browsePageKey = "item:" + kind + ":" + id
    browsePage = null
    browseTitleHint = title || ""
    // names the crumb until the payload lands
    browseArtHint = art || ""
    // faces the hero until the payload lands
    browsePageError = false
    browsePageLoading = true
    waves.openBrowseItem(kind, id)
  }
  function browseBack() {
    browsePageLoading = false
    browsePageError = false
    browseHighlightId = ""
    browseTitleHint = ""
    browseArtHint = ""
    if (browseStack.length > 0) {
      var s = browseStack.slice()
      var prev = s.pop()
      browseStack = s
      browsePage = prev
      browsePageKey = prev.key
    } else {
      // Home: flip the landing visible. browsePage stays set so the
      // page just left survives behind it (see _navRestore).
      browsePageKey = ""
    }
  }
  // A track title anywhere (search, library, artist, browse) leads to its
  // album's browse page with the track highlighted, from outside Browse
  // too, so switch the tab in.
  // True when the browse album page for `albumId` is what's on screen,
  // its title links go inert then (clicking "go to album" on the album
  // you're already reading shouldn't re-navigate or grow the Back stack).
  function onAlbumPage(albumId) {
    return browseOpen && !artistOpen && !settingsOpen && !libraryOpen && browsePageKey === "item:album:" + albumId
  }
  // Same idea for artist links: inert while that artist's page is open.
  function onArtistPage(artistId) {
    return artistOpen && artistData && ("" + artistData.id) === ("" + artistId)
  }
  function openAlbumPage(albumId, highlight, title, art) {
    if (!albumId || onAlbumPage(albumId))
      return
    markNav("browse")
    openBrowseItem("album", albumId, highlight || "", title || "", art || "")
    // snapshots the view being left
    settingsOpen = false
    setupOpen = false
    artistOpen = false
    libraryOpen = false
    browseOpen = true
    if (root.signedIn && browseSections.length === 0 && !browseLoading) {
      browseLoading = true
      browseError = false
      waves.loadBrowse()
    }
  }
  // Same page for a playlist from anywhere (My Music rows included): the
  // synthesized art-header + track-list browse page, switching the Browse
  // surface in just like openAlbumPage does for albums.
  function openPlaylistPage(playlistId, title, art) {
    if (!playlistId)
      return
    if (browseOpen && !artistOpen && !settingsOpen && !libraryOpen && browsePageKey === "item:playlist:" + playlistId)
      return
    markNav("browse")
    openBrowseItem("playlist", playlistId, "", title || "", art || "")
    settingsOpen = false
    setupOpen = false
    artistOpen = false
    libraryOpen = false
    browseOpen = true
    if (root.signedIn && browseSections.length === 0 && !browseLoading) {
      browseLoading = true
      browseError = false
      waves.loadBrowse()
    }
  }
  // Where a card's art leads: artists to the artist page; albums, playlists
  // and mixes to their own synthesized page; tracks to their album's page
  // with the track highlighted (falling back to the artist page for the
  // rare track without an album id). A video card, or a track naming
  // neither an album nor an artist, goes nowhere.
  // browseCardOpenable is the one verdict the cards' affordance (cursor,
  // underline) and the click path below both read, so the two can never
  // disagree. A track offers its page when it names an album or an
  // artist; anything else stays inert.
  function browseCardOpenable(card) {
    var kind = card.kind || ""
    if (kind === "artist" || kind === "playlist" || kind === "mix" || kind === "album")
      return true
    if (kind === "track")
      return !!(card.album_id || card.artist_id)
    return false
  }
  function openBrowseCard(card) {
    if (!browseCardOpenable(card))
      return
    var kind = card.kind || ""
    // The artist page switches the active surface itself in onArtistLoaded,
    // so those branches return before the browse-surface flip below.
    if (kind === "artist") {
      waves.loadArtist(card.id)
      return
    }
    if (kind === "playlist" || kind === "mix" || kind === "album") {
      openBrowseItem(kind, card.id, "", card.title || "", card.art || "")
    } else if (kind === "track") {
      // A track card's art is its album's cover (smaller), still the right face.
      // The guard above already settled that an album or an artist is named,
      // so the artist test is implied; the return is not: the artist page
      // switches the surface itself, like the artist branch above, and must
      // skip the browse-surface flip below.
      if (card.album_id)
        openBrowseItem("album", card.album_id, card.id, card.album || "", card.art || "")
      else {
        waves.loadArtist(card.artist_id)
        return
      }
    } else
      return
    // This card is reused on My Music's Home shelves, which live in the
    // library pane, so make Browse the active surface; when the click came
    // from within Browse these flags are already set, so it is a no-op.
    browseOpen = true
    settingsOpen = false
    setupOpen = false
    artistOpen = false
    libraryOpen = false
  }
  // Browse rows carry per-item `artists` arrays; stash them in the same
  // artistsById side map the search/library rows use, so ArtistLinks inside
  // reused components (TrackRow) resolve for browse items too.
  function browseArtistsSideMap(sections) {
    var m = root.artistsById
    for (var s = 0; s < sections.length; ++s) {
      var items = sections[s].items || []
      for (var i = 0; i < items.length; ++i)
        if (items[i].artists)
          m[items[i].id] = items[i].artists
    }
    root.artistsById = m
  }

  // The one and only audio player. Every preview button drives this single
  // instance, so starting a new preview structurally replaces the old one.
  MediaPlayer {
    id: previewPlayer
    audioOutput: AudioOutput {
      id: previewOut
    }
    // Optional stop: previewStopMs > 0 caps the clip (default 30s); 0 lets
    // the whole track play. Both leave the same idle state via stopPreview.
    onPositionChanged: {
      // While scrubbing, the fill tracks the cursor, don't let the
      // player's clock stomp it back to the pre-seek spot.
      if (!root.previewScrubbing)
        root.previewPosition = previewPlayer.position
      if (root.previewStopMs > 0 && previewPlayer.position >= root.previewStopMs)
        root.stopPreview()
    }
    onDurationChanged: root.previewDuration = previewPlayer.duration
    onPlaybackStateChanged: {
      root.previewPlaying = (playbackState === MediaPlayer.PlayingState)
      if (playbackState !== MediaPlayer.StoppedState)
        root.previewLoading = false
    }
    onMediaStatusChanged: {
      // Whole-track end resolves to the SAME idle state as the 30s cap.
      if (mediaStatus === MediaPlayer.EndOfMedia)
        root.stopPreview()
    }
    onErrorOccurred: function (err, errStr) {
      // Playback/network failure on a resolved source, flash red like a
      // failed resolve, then fall back to idle. Logged for diagnosis.
      waves.uiLog("preview", "player error " + err + ": " + errStr, -1)
      if (root.previewId !== "")
        root.previewError = root.previewKind + ":" + root.previewId
      root.stopPreview()
      if (root.previewError !== "")
        previewErrorTimer.restart()
    }
  }

  // ====================================================================
  // Video player overlay (deliberately simple for first ship)
  // ====================================================================
  // Quality-switch seek, verify-and-retry. A one-shot seek fired from a
  // readiness signal can be swallowed: the signals often belong to the DYING
  // old stream, the ffmpeg backend drops setPosition while the new source is
  // still loading, and the code then believes the seek landed, which reads as
  // restarts plus a frozen frame. These HLS
  // variants seek fine once actually loaded, so this timer re-seeks every
  // 300 ms and only stops when the OBSERVED position reaches the target
  // (or it gives up after ~6 s and lifts the freeze).
  property var _videoGrab: null        // grabToImage result, kept alive while frozen
  property real _videoSeekTarget: -1   // where the freeze-frame lifts
  property int _videoSeekTries: 0
  function _videoSwapDone() {
    videoFreeze.visible = false
    _videoGrab = null
    _videoSeekTarget = -1
    videoPendingSeek = -1
    videoSeekRetry.stop()
  }
  Timer {
    id: videoSeekRetry
    interval: 300
    repeat: true
    onTriggered: {
      if (root.videoPendingSeek <= 0 || !root.videoNow) {
        root._videoSwapDone()
        return
      }
      if (++root._videoSeekTries > 20) {
        root._videoSwapDone()
        return
      }  // give up, show live stream
      if (videoPlayer.mediaStatus !== MediaPlayer.LoadedMedia && videoPlayer.mediaStatus !== MediaPlayer.BufferedMedia)
        // new source not ready yet
        return
      if (videoPlayer.position >= root.videoPendingSeek - 2000) {
        // Verified: playback is actually at (or past) the target.
        root._videoSeekTarget = root.videoPendingSeek
        root.videoPendingSeek = -1
        // freeze lifts in onPositionChanged
        return
      }
      if (videoPlayer.duration > 0)
        videoPlayer.position = Math.min(root.videoPendingSeek, videoPlayer.duration - 500)
    }
  }
  // Lifts the frame grabbed from the peek card once the adopted pipeline is
  // painting the overlay's stage (the sink move takes a frame or two).
  Timer {
    id: videoFreezeLift
    interval: 260
    onTriggered: {
      videoFreeze.visible = false
      root._videoGrab = null
    }
  }
  // Promotion upgrade, park and meet.
  //
  // Cutting on POSITION alone is not enough: position reports a seek target
  // the instant it is set, while the sink still holds whatever frame it had
  // before (for a stream that just started, frame one). The swap would then
  // flash the first frame for a beat
  // before the seeked picture arrived. So the upgrade does not chase: it
  // parks PAUSED a couple of seconds AHEAD of the live clock, which makes
  // the backend decode and present that exact frame into the off-stage
  // sink, and the cut waits until the peek's own clock reaches the parked
  // frame. Both sides are then showing the same moment, and the swap is a
  // true continuation with nothing stale to reveal.
  property int _videoUpTries: 0
  property int _videoUpAims: 0
  property int _videoUpPhase: 0     // 0 opening, 1 seeking to the park, 2 parked and waiting
  property real _videoUpTarget: -1
  function _videoUpAimAt(t) {
    if (++_videoUpAims > 6) {
      _videoUpgradeGiveUp()
      return
    }
    // Not enough runway left to stage a handover before the video ends.
    if (videoPlayer.duration > 0 && t > videoPlayer.duration - 800) {
      _videoUpgradeGiveUp()
      return
    }
    _videoUpTarget = Math.max(0, t)
    _videoUpPhase = 1
    videoPlayer.pause()
    videoPlayer.position = _videoUpTarget
  }
  Timer {
    id: videoUpgradeRetry
    interval: 60
    repeat: true
    onTriggered: {
      if (!root.videoUpgrading || !root.videoFromPeek || !root.videoNow) {
        root._videoUpgradeGiveUp()
        return
      }
      if (++root._videoUpTries > 250) {
        root._videoUpgradeGiveUp()
        return
      }   // ~15s, stay on the glance stream
      if (videoPlayer.mediaStatus !== MediaPlayer.LoadedMedia && videoPlayer.mediaStatus !== MediaPlayer.BufferedMedia)
        return
      var live = peekPlayer.position
      var playing = peekPlayer.playbackState === MediaPlayer.PlayingState
      if (root._videoUpPhase === 0) {
        // First moment the new stream is usable: park it ahead of the
        // live clock (or right on it, when the peek is paused).
        root._videoUpAimAt(playing ? live + 2000 : live)
        return
      }
      if (root._videoUpPhase === 1) {
        // Parked once the seek has actually landed, which is also when
        // the sink is holding the frame we are going to reveal.
        if (Math.abs(videoPlayer.position - root._videoUpTarget) <= 250) {
          root._videoUpPhase = 2
          return
        }
        // The live clock overtook the park before the seek landed
        // (slow seek, or the user jumped forward): aim further ahead.
        if (playing && live > root._videoUpTarget - 250)
          root._videoUpAimAt(live + 2000 * (root._videoUpAims + 1))
        return
      }
      // Parked and holding: meet the live clock at that exact frame.
      if (!playing) {
        if (Math.abs(videoPlayer.position - live) <= 250) {
          root._videoCut()
          return
        }
        root._videoUpAimAt(live)
        // paused somewhere else, re-park on the spot
        return
      }
      if (live >= root._videoUpTarget - 40)
        root._videoCut()
    }
  }
  MediaPlayer {
    id: videoPlayer
    videoOutput: vsA
    audioOutput: AudioOutput {
      id: videoOut
    }
    onPositionChanged: {
      // Lift the freeze-frame only once playback has actually reached the
      // restored spot, the blank/black gap stays hidden the whole time.
      if (videoFreeze.visible && root.videoPendingSeek < 0 && root._videoSeekTarget >= 0 && position >= root._videoSeekTarget - 2000) {
        videoFreeze.visible = false
        root._videoGrab = null
        root._videoSeekTarget = -1
      }
    }
    onErrorOccurred: function (err, errStr) {
      waves.uiLog("video", "player error " + err + ": " + errStr, -1)
      root._videoSwapDone()
      // A failed UPGRADE is invisible: the peek's pipeline is on stage
      // and playing, so the video just stays at glance resolution.
      if (root.videoUpgrading) {
        root._videoUpgradeGiveUp()
        return
      }
      if (root.videoNow) {
        root.videoError = true
        root.videoLoading = false
      }
    }
  }
  // ==== Hover video peek card =========================================
  // Grows out of the hovered thumbnail's mapped rect into a 16:9 card
  // centered on it (clamped inside the window). The thumbnail's own art
  // holds the surface until frames arrive so the growth never reveals a
  // black panel; sound eases in rather than blasting. Sits under the full
  // player overlay (z 999) so opening the real player covers it.
  MediaPlayer {
    id: peekPlayer
    videoOutput: peekSurface
    audioOutput: AudioOutput {
      volume: root.peekReady ? 1 : 0
      Behavior on volume {
        NumberAnimation {
          duration: 420
        }
      }
    }
    onPlaybackStateChanged: {
      if (playbackState === MediaPlayer.PlayingState) {
        root.peekReady = true
        // One thing sounds at a time (same rule as the full player),
        // but a hover glance only pauses a running track preview, it
        // never tears the preview down.
        if (previewPlayer.playbackState === MediaPlayer.PlayingState)
          previewPlayer.pause()
      }
    }
    onMediaStatusChanged: {
      if (mediaStatus !== MediaPlayer.EndOfMedia)
        return
      // Once promoted this player IS the overlay, so its end is the
      // video's end, not a hover ending.
      if (root.videoFromPeek)
        root.closeVideo()
      else
        root.peekClose()
    }
    onErrorOccurred: function (err, errStr) {
      // A failed glance just goes away, no error chrome on a hover.
      waves.uiLog("video", "peek player error " + err + ": " + errStr, -1)
      if (root.videoFromPeek)
        root._videoPromotionLost()
      else
        root.peekClose()
    }
  }
  Rectangle {
    id: peekCard
    z: 990
    visible: root.peekNow !== null
    color: "#0b0d10"
    radius: 8
    border.color: root.border1
    border.width: 1
    clip: true
    function growFrom(ax, ay, aw, ah) {
      peekGrow.stop()
      x = ax
      y = ay
      width = aw
      height = ah
      // Grow relative to the source: a 88px row thumb keeps the old
      // 360 card, a search-grid thumb steps up from its own size so the
      // peek still reads as an expansion rather than a shrink.
      var tw = Math.min(Math.max(360, aw + 80), root.width - 24)
      var th = Math.round(tw * 9 / 16)
      gx.to = Math.max(12, Math.min(ax + aw / 2 - tw / 2, root.width - tw - 12))
      gy.to = Math.max(12, Math.min(ay + ah / 2 - th / 2, root.height - th - 12))
      gw.to = tw
      gh.to = th
      peekGrow.start()
    }
    ParallelAnimation {
      id: peekGrow
      NumberAnimation {
        id: gx
        target: peekCard
        property: "x"
        duration: 240
        easing.type: Easing.OutCubic
      }
      NumberAnimation {
        id: gy
        target: peekCard
        property: "y"
        duration: 240
        easing.type: Easing.OutCubic
      }
      NumberAnimation {
        id: gw
        target: peekCard
        property: "width"
        duration: 240
        easing.type: Easing.OutCubic
      }
      NumberAnimation {
        id: gh
        target: peekCard
        property: "height"
        duration: 240
        easing.type: Easing.OutCubic
      }
    }
    VideoOutput {
      id: peekSurface
      anchors.fill: parent
      anchors.margins: 1
      fillMode: VideoOutput.PreserveAspectCrop
      opacity: root.peekReady ? 1 : 0
      Behavior on opacity {
        NumberAnimation {
          duration: 180
        }
      }
    }
    // Waiting surface: rather than blowing the thumbnail up to a size it
    // was never made for, the card waits on its own with a game of snake
    // running quietly behind the label.
    Item {
      anchors.fill: parent
      anchors.margins: 1
      visible: !root.peekReady
      SnakeField {
        anchors.fill: parent
        running: parent.visible && root.peekNow !== null
        plateW: peekWaitPlate.width
        plateH: peekWaitPlate.height
        opacity: 0.85
      }
      Rectangle {
        id: peekWaitPlate
        anchors.centerIn: parent
        radius: 6
        color: "#cc06090c"
        border.color: root.border1
        border.width: 1
        // Sized for the label with all its dots, so the plate (and
        // the snake's ring around it) never shifts as they march.
        implicitWidth: peekWaitTm.width + 26
        implicitHeight: 30
        TextMetrics {
          id: peekWaitTm
          font: peekWaitTx.font
          text: "LOADING VIDEO..."
        }
        Text {
          id: peekWaitTx
          anchors.left: parent.left
          anchors.leftMargin: 13
          anchors.verticalCenter: parent.verticalCenter
          // The dots march instead of the label pulsing: one clock,
          // no fade to fight the snake behind it.
          textFormat: Text.PlainText
          text: "LOADING VIDEO" + ".".repeat(peekWaitDots.tick)
          color: root.textLo
          font.family: root.mono
          font.pixelSize: 11
          font.bold: true
        }
        Timer {
          id: peekWaitDots
          property int tick: 0
          running: parent.visible
          interval: 380
          repeat: true
          onTriggered: tick = (tick + 1) % 4
        }
      }
    }
    HoverHandler {
      id: peekCardHover
      onHoveredChanged: root.peekHoverCheck()
    }
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: {
        // Playing: hand the live pipeline over, no gap, no restart.
        // Still resolving: nothing to adopt, so open cold.
        if (root.peekReady) {
          root.promoteVideo()
          return
        }
        var p = root.peekNow
        root.peekClose()
        if (p)
          root.openVideo(p.id, p.title, p.artist)
      }
      // A scroll is page navigation, not a peek interaction. The card
      // grows centred on the thumb, i.e. right under the cursor, so
      // swallowing the wheel froze scrolling wherever a peek was open.
      // Let the glance go and hand the event on to the page.
      onWheel: function (w) {
        root.peekClose()
        w.accepted = false
      }
    }
  }
  Shortcut {
    sequence: "Esc"
    enabled: root.peekNow !== null && root.videoNow === null
    onActivated: root.peekClose()
  }
  Shortcut {
    sequence: "Esc"
    enabled: root.videoNow !== null
    onActivated: root.closeVideo()
  }
  // The inline TIDAL sign-in's keyboard exit, the same as its CANCEL
  // button. Only while the welcome surface is the one on screen.
  Shortcut {
    sequence: "Esc"
    enabled: root.setupMode === "tidal" && (root.setupOpen || root.welcomeDue) && root.peekNow === null && root.videoNow === null
    onActivated: root.cancelSetupSignIn()
  }
  Shortcut {
    sequence: "Space"
    enabled: root.videoNow !== null && !root.videoLoading && !root.videoError
    onActivated: root.vPlayer.playbackState === MediaPlayer.PlayingState ? root.vPlayer.pause() : root.vPlayer.play()
  }
  Rectangle {
    anchors.fill: parent
    z: 999
    visible: root.videoNow !== null
    color: "#e0000000"
    // Click outside the card closes; swallow wheel so pages don't scroll.
    MouseArea {
      anchors.fill: parent
      onClicked: root.closeVideo()
      onWheel: function (w) {
        w.accepted = true
      }
    }
    Rectangle {
      id: videoCard
      anchors.centerIn: parent
      width: Math.min(parent.width - 72, 960)
      height: Math.min(Math.round((width - 2) * 9 / 16), parent.height - 140) + 46
      color: "#0b0d10"
      radius: 10
      border.color: root.border1
      border.width: 1
      clip: true
      MouseArea {
        anchors.fill: parent
      }   // swallow clicks inside the card
      // Two stacked sinks, one on stage. A single player uses A and B
      // never renders; a promoted peek plays A while the upgrade warms
      // up on B, and the cut is one opacity flip (see _videoCut). Both
      // always exist as real sinks so the warming stream has somewhere
      // to decode into, it just is not painted.
      Item {
        id: videoStage
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 1
        height: parent.height - 46
        VideoOutput {
          id: vsA
          anchors.fill: parent
          opacity: root.videoOnB ? 0 : 1
        }
        VideoOutput {
          id: vsB
          anchors.fill: parent
          opacity: root.videoOnB ? 1 : 0
        }
      }
      // Held over the stage whenever a swap could show a blank panel: a
      // quality switch (last frame of the outgoing stream) or the peek
      // handover (last frame of the card).
      Image {
        id: videoFreeze
        visible: false
        anchors.fill: videoStage
        fillMode: Image.PreserveAspectFit
        cache: false
      }
      // Click anywhere on the picture to toggle play/pause.
      MouseArea {
        anchors.fill: videoStage
        onClicked: root.vPlayer.playbackState === MediaPlayer.PlayingState ? root.vPlayer.pause() : root.vPlayer.play()
      }
      // GET / ERR states, in the terminal voice of the Art placeholders.
      Text {
        anchors.centerIn: videoStage
        visible: root.videoLoading || root.videoError
        textFormat: Text.PlainText
        text: root.videoError ? "ERR  stream unavailable" : "GET  video stream…"
        color: root.videoError ? root.red : root.accentDim
        font.family: root.mono
        font.pixelSize: 13
      }
      // Controls bar: play/pause, seek, time, title, close.
      Item {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 46
        RowLayout {
          anchors.fill: parent
          anchors.leftMargin: 14
          anchors.rightMargin: 10
          spacing: 12
          Text {
            textFormat: Text.PlainText
            text: root.vPlayer.playbackState === MediaPlayer.PlayingState ? "[||]" : "[>]"
            color: root.accent
            font.family: root.mono
            font.pixelSize: 14
            MouseArea {
              anchors.fill: parent
              anchors.margins: -6
              cursorShape: Qt.PointingHandCursor
              enabled: !root.videoLoading && !root.videoError
              onClicked: root.vPlayer.playbackState === MediaPlayer.PlayingState ? root.vPlayer.pause() : root.vPlayer.play()
            }
          }
          // Seek bar: click or drag anywhere on the track.
          Rectangle {
            Layout.fillWidth: true
            height: 5
            radius: 2
            color: root.surface3
            Rectangle {
              width: root.vPlayer.duration > 0 ? parent.width * root.vPlayer.position / root.vPlayer.duration : 0
              height: parent.height
              radius: 2
              color: root.accent
            }
            MouseArea {
              anchors.fill: parent
              anchors.margins: -8
              enabled: root.vPlayer.seekable
              function seekTo(x) {
                var w = width - 16
                if (w > 0 && root.vPlayer.duration > 0)
                  root.vPlayer.position = Math.max(0, Math.min(1, (x - 8) / w)) * root.vPlayer.duration
              }
              onPressed: function (m) {
                seekTo(m.x)
              }
              onPositionChanged: function (m) {
                if (pressed)
                  seekTo(m.x)
              }
            }
          }
          Text {
            textFormat: Text.PlainText
            text: root.fmtMs(root.vPlayer.position) + " / " + root.fmtMs(root.vPlayer.duration)
            color: root.textLo
            font.family: root.mono
            font.pixelSize: 11
          }
          // Title -> the video's album page (when TIDAL links one).
          Text {
            id: vpTitle
            readonly property bool linkable: root.videoNow !== null && (root.videoNow.albumId || "") !== ""
            textFormat: Text.PlainText
            Layout.maximumWidth: videoCard.width * 0.22
            text: root.videoNow ? (root.videoNow.title || "") : ""
            color: vpTitleMa.containsMouse && vpTitle.linkable ? "#ffffff" : root.textHi
            font.pixelSize: 12
            elide: Text.ElideRight
            MouseArea {
              id: vpTitleMa
              anchors.fill: parent
              hoverEnabled: true
              enabled: vpTitle.linkable
              cursorShape: vpTitle.linkable ? Qt.PointingHandCursor : Qt.ArrowCursor
              onClicked: {
                // Highlight the matching track when the album was
                // found via the song lookup, else the video id.
                var a = root.videoNow.albumId
                var t = root.videoNow.trackId || root.videoNow.id
                root.closeVideo()
                root.openAlbumPage(a, t)
              }
            }
          }
          // Artist credits: the shared green links (navigating closes
          // the player, see onArtistLoaded).
          ArtistLinks {
            host: root
            Layout.maximumWidth: videoCard.width * 0.2
            artists: root.videoNow ? (root.videoNow.artists || []) : []
          }
          // Quality: green like the artist links; opens the resolution menu.
          Text {
            id: vqLabel
            textFormat: Text.PlainText
            // Hidden while a promotion upgrade is in flight: the
            // resolution is about to change on its own, and a
            // manual pick would race that resolve.
            visible: root.videoNow !== null && !root.videoUpgrading && !root.videoFromPeek
            text: root.videoSwitching ? "…" : root.videoNow && root.videoNow.res ? root.videoNow.res + "p" : "AUTO"
            color: root.accent
            font.family: root.mono
            font.pixelSize: 11
            font.underline: vqMa.containsMouse || vqMenu.visible
            MouseArea {
              id: vqMa
              anchors.fill: parent
              anchors.margins: -6
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: vqMenu.visible = !vqMenu.visible
            }
          }
          Text {
            id: vpClose
            textFormat: Text.PlainText
            text: "[x]"
            color: vpCloseMa.containsMouse ? "#ff7b74" : root.red
            font.family: root.mono
            font.pixelSize: 14
            MouseArea {
              id: vpCloseMa
              anchors.fill: parent
              anchors.margins: -6
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.closeVideo()
            }
          }
        }
      }
      // Resolution picker, floating just above the controls bar.
      Rectangle {
        id: vqMenu
        visible: false
        width: 78
        height: vqCol.implicitHeight + 14
        radius: 8
        color: root.surface0
        border.color: root.outline
        border.width: 1
        // Open directly above the quality label, wherever the controls
        // row happens to have laid it out.
        onVisibleChanged: if (visible) {
          var p = vqLabel.mapToItem(videoCard, vqLabel.width / 2, 0)
          x = Math.max(8, Math.min(videoCard.width - width - 8, p.x - width / 2))
          y = videoCard.height - 46 - height - 6
        }
        Column {
          id: vqCol
          anchors.centerIn: parent
          spacing: 3
          Repeater {
            // Only what this video's playlist actually offers.
            model: root.videoNow && (root.videoNow.heights || []).length ? root.videoNow.heights : [1080, 720, 480, 360]
            delegate: Text {
              id: vqOpt
              required property var modelData
              textFormat: Text.PlainText
              width: 62
              horizontalAlignment: Text.AlignHCenter
              text: modelData + "p"
              color: root.videoNow && root.videoNow.res === modelData ? root.accent : vqOptMa.containsMouse ? root.textHi : root.textLo
              font.family: root.mono
              font.pixelSize: 12
              MouseArea {
                id: vqOptMa
                anchors.fill: parent
                anchors.margins: -3
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                  vqMenu.visible = false
                  root.changeVideoQuality(vqOpt.modelData)
                }
              }
            }
          }
        }
      }
    }
  }

  // ====================================================================
  // Warm cover-art pool
  // ====================================================================
  // Qt only keeps a small budget of decoded-but-unreferenced images, so
  // revisiting a page would re-decode every cover (the placeholder→art
  // pop-in that makes every visit feel like a first load). This invisible
  // pool holds a live Image for the last ~220 covers shown, keeping their
  // decoded pixels referenced in the pixmap cache, a rebuilt delegate with
  // the same url+sourceSize+fillMode then paints instantly. Oldest warmed
  // out first (a cover shown again does not move back to the end). The pool
  // shares each pixmap with whatever is on screen rather than holding a copy
  // of it, so what it costs is only the covers that have left the page:
  // worst case ~100 MB of RAM at typical tile sizes, usually far less.
  // Each row carries `ready`: false until the pool's own Image has decoded
  // it. A cover being listed is not a cover being warm; the hover scenario
  // waits for `ready` before clicking, so its assertion measures the
  // prefetch, not a race against the decoder.
  // The track disc's decode size, in one place: PreviewArt asks for it and
  // the prefetch handler warms at it, and the pool keys on the exact size,
  // so two literals that drift apart would silently warm nothing.
  readonly property int discDecode: 68
  property var _warmSeen: ({})   // "url@w" -> true; mutated in place (nothing binds to it)
  function warmArt(u, w, h) {
    if (!u || w <= 0)
      return
    var k = u + "@" + w
    if (_warmSeen[k])
      return
    _warmSeen[k] = true
    warmArtModel.append({
      u: "" + u,
      w: w,
      h: h,
      ready: false
    })
    if (warmArtModel.count > 220) {
      var old = warmArtModel.get(0)
      delete _warmSeen[old.u + "@" + old.w]
      warmArtModel.remove(0)
    }
  }
  ListModel {
    id: warmArtModel
  }
  Item {
    visible: false
    Repeater {
      model: warmArtModel
      Image {
        source: model.u
        sourceSize.width: model.w
        sourceSize.height: model.h
        // Qt keys the pixmap cache on the FILL MODE as well as the url
        // and the decode size: PreserveAspectCrop and PreserveAspectFit
        // each raise their own flag in the load request, and an entry
        // stored under one is never handed to the other. Left at the
        // default (Stretch) this pool therefore fetched and decoded a
        // SECOND copy of every cover and pinned that, while the copy
        // the page had actually painted stayed unpinned and fell out
        // of Qt's ~2 MB budget for no-longer-shown pixmaps (measured
        // here: 40-60 thumbnails, i.e. one page of results), so a
        // revisit went back to the loading placeholder exactly as if
        // the pool did not exist. Every art surface crops (Art,
        // PreviewArt, MosaicCell, the browse header), so cropping here
        // is what pins the pixmap the next page will ask for.
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        visible: false
        // The row's own decode flag (see the pool comment above): the
        // hover scenario polls it to know the pool is actually warm.
        // The row is re-read because a load that outlives an eviction
        // shift must not mark another row ready; `w` is half of the
        // pool key (a url is deliberately warmed at two widths), so
        // the identity is the whole key, not the url alone.
        onStatusChanged: if (status === Image.Ready) {
          var i = index
          if (i >= 0 && i < warmArtModel.count && warmArtModel.get(i).u === ("" + source) && warmArtModel.get(i).w === sourceSize.width)
            warmArtModel.setProperty(i, "ready", true)
        }
      }
    }
  }

  // ====================================================================
  // Hover prefetch
  // ====================================================================
  // A pointer resting on a playlist / mix / album card is about to open
  // it. After a short dwell the card's cover is warmed at the hero's
  // decode size and the backend builds the page (prefetchBrowseItem,
  // silent, one at a time), so the click that follows paints from the
  // cache: no "Reading the wire…", no "art: GET". ONE shared timer and
  // one pending target: 200 ms of unbroken hover, above the 90 ms tilt
  // arm and for the same reason (a shelf sliding under a still cursor
  // must not fetch every card it passes). Leaving the card before the
  // dwell ends cancels it. Track rows ask for a longer dwell: clicking
  // one opens its album page, but a pointer parked on a row while
  // reading is not a click coming. Artist cards take the same dwell to
  // their own builder (prefetchArtist): a heavier page, cached on disk
  // across launches, so only an artist never visited pays, and the
  // hover pays it before the click.
  property string _hoverPrefetchKey: ""
  property var _hoverPrefetchCard: null
  function _cardPrefetchKey(card) {
    if (!card)
      return ""
    var kind = card.kind || ""
    if (kind === "track")
      return card.album_id ? "album:" + card.album_id : ""
    if (kind === "playlist" || kind === "mix" || kind === "album" || kind === "artist")
      return card.id ? kind + ":" + card.id : ""
    // An album ROW (AlbumBlock): the click that follows expands it in
    // place, so what is warmed is its inline track list, not its page.
    if (kind === "album_tracks")
      return card.id && !root.trackCache[card.id] ? "album_tracks:" + card.id : ""
    return ""
  }
  // dwell defaults to the card rest; a caller can ask for a longer one where
  // the pointer sits by accident more often than on purpose (track rows).
  function hoverPrefetch(card, dwell) {
    if (!root.signedIn)
      return
    var k = _cardPrefetchKey(card)
    if (k === "" || root.browsePageKey === "item:" + k)
      // not a page, or already on it
      return
    if (root.artistOpen && root.artistData && k === "artist:" + root.artistData.id)
      // the page under the pointer
      return
    _hoverPrefetchKey = k
    _hoverPrefetchCard = card
    hoverPrefetchTimer.interval = dwell > 0 ? dwell : 200
    hoverPrefetchTimer.restart()
  }
  // By the card object, not its key: every track row of one album shares
  // the album's key, and crossing between two adjacent rows delivers the
  // entered row's arm before the left row's cancel, so a cancel keyed on
  // the album killed the arm it did not own and reading down an album's
  // rows never prefetched it. Each row's card is its own object.
  function hoverPrefetchCancel(card) {
    if (_hoverPrefetchCard !== null && _hoverPrefetchCard === card) {
      hoverPrefetchTimer.stop()
      _hoverPrefetchKey = ""
      _hoverPrefetchCard = null
    }
  }
  Timer {
    id: hoverPrefetchTimer
    interval: 200
    onTriggered: {
      var c = root._hoverPrefetchCard, k = root._hoverPrefetchKey
      root._hoverPrefetchKey = ""
      root._hoverPrefetchCard = null
      if (!c || k === "")
        return
      // The page hero is a 180px Art, decodeW 360 (the artist page's
      // photo is 150px, decodeW 300): warm the card's cover at that
      // size so the stand-in is a pixmap hit.
      var cut = k.indexOf(":")
      var kind = k.substring(0, cut), id = k.substring(cut + 1)
      if (c.art)
        root.warmArt("" + c.art, kind === "artist" ? 300 : 360, kind === "artist" ? 300 : 360)
      if (kind === "album_tracks")
        waves.prefetchAlbumTracks(id)
      else if (kind === "artist")
        waves.prefetchArtist(id)
      else
        waves.prefetchBrowseItem(kind, id)
    }
  }

  // ====================================================================
  // Reusable components
  // ====================================================================

  // One colour-coded badge carrying the quality tier and, when known, its
  // format spec (e.g. "LOSSLESS 16/44.1", "HI-RES 24-bit"). The spec rides in
  // a dimmer shade of the same tier colour, so the tier stays prominent while
  // spelling out what that tier means for this specific album/track.
  // Tier counts for a loaded track list: [] when uniform, else
  // [{q, n}, ...] best-tier-first, drives the MIXED variant of QualTag.
  function qualMixList(tracks) {
    var counts = {}
    for (var i = 0; i < tracks.length; ++i) {
      var q = tracks[i].quality || ""
      if (q !== "")
        counts[q] = (counts[q] || 0) + 1
    }
    var keys = Object.keys(counts)
    if (keys.length < 2)
      return []
    var rank = {
      "HI-RES": 0,
      "LOSSLESS": 1,
      "HIGH": 2
    }
    keys.sort(function (a, b) {
      return (rank[a] !== undefined ? rank[a] : 9) - (rank[b] !== undefined ? rank[b] : 9)
    })
    return keys.map(function (k) {
      return {
        q: k,
        n: counts[k]
      }
    })
  }

  // The tier one line of an expanded album states: what the file landed at
  // once it has landed, and until then what the job is ASKING for, which the
  // caller renders faded.
  //
  // "pending" has to be in that second group and was not: it is the state a
  // fetched track list starts in (_merge_queue_tracks defaults to it) and so
  // it is every track of a queued album and every not-yet-started track of a
  // running one, which is precisely the stretch where the only thing to say
  // is the request. Without it the column sat blank until each track's turn
  // came. A track that is cancelled or failed says nothing: no tier was ever
  // delivered for it, and the request is not news about a file that is not
  // coming. A skipped track (IN LIBRARY) states the copy you already hold:
  // its skip event carries that copy's tier as the delivery, full strength,
  // since it is what the file IS rather than what a fetch is asking for.
  // The lower of two tiers: what a download will most likely land at when
  // the request is one and the catalog's advertised ceiling is the other.
  // Either side empty yields the other; a word neither ranks yields the
  // request, since that is at least what the job asked for.
  readonly property var _tierRank: ({
      "HI-RES": 0,
      "LOSSLESS": 1,
      "HIGH": 2,
      "LOW": 3
    })
  function tierFloor(request, ceiling) {
    request = "" + (request || "")
    ceiling = "" + (ceiling || "")
    if (request === "")
      return ceiling
    if (ceiling === "")
      return request
    var r = _tierRank[request], c = _tierRank[ceiling]
    if (r === undefined || c === undefined)
      return request
    return c > r ? ceiling : request
  }
  // The tier a ledger row states: the delivery once a file has landed, and
  // before that the honest prediction, the request floored by the track's
  // advertised ceiling. A finished row with neither says nothing.
  function queueTrackTier(delivered, status, target, expected) {
    if (delivered !== "")
      return delivered
    if (status !== "pending" && status !== "queued" && status !== "running")
      return ""
    return tierFloor(target, expected)
  }

  // ownership batch listening
  // The bridge announces cold-cache ownership answers in batches
  // (ownershipChangedBatch: one ",id1,id2,...," string per flush), because
  // per-id signals at launch ran every listening card's handler for every
  // one of ~1500 answers. A listener precomputes the keys of the ids it
  // cares about (",id,") once, when it learns them, and tests a batch with
  // that many substring searches: no allocation, no walk of a bridge list
  // (indexOf on a QVariantList converts every element on every call, and
  // those conversions were what forced the JS garbage collector mid-launch).
  function ownKeys(ids) {
    if (!ids)
      return null
    var out = []
    for (var i = 0; i < ids.length; ++i)
      out.push("," + ids[i] + ",")
    return out
  }
  function ownBatchHits(batch, keys) {
    if (!keys)
      return false
    for (var i = 0; i < keys.length; ++i)
      if (batch.indexOf(keys[i]) !== -1)
        return true
    return false
  }
  // The art cards' ownership re-ask, batched: when a batch of first
  // answers lands, every card whose members are in it would otherwise ask
  // the bridge for its own rollup, one QML-to-Python call per card (~130 on
  // a fresh landing, each waiting its turn for the interpreter behind the
  // launch workers, a run of 50-80 ms GUI-thread holds right after the
  // cards appeared). Cards register their collection id and member keys
  // here instead; one call answers every hit card at once, and the cards
  // read their answer off ownAnswers.
  property var _ownCards: ({})      // cid -> [",id,", ...] member keys (or null)
  property var ownAnswers: ({})     // cid -> {ids, verdict}, the last batch's answers
  property int ownAnswersGen: 0
  function ownCardRegister(cid, keys) {
    if (cid)
      _ownCards[cid] = keys || null
  }
  function ownCardForget(cid) {
    if (cid && cid in _ownCards)
      delete _ownCards[cid]
  }
  function ownCardsBatch(batch) {
    var hit = []
    for (var cid in _ownCards) {
      var keys = _ownCards[cid]
      if (!keys)
        continue
      for (var i = 0; i < keys.length; ++i)
        if (batch.indexOf(keys[i]) !== -1) {
          hit.push(cid)
          break
        }
    }
    if (hit.length === 0)
      return
    ownAnswers = waves.collectionOwnershipMany(hit)
    ownAnswersGen++
  }
  // Which forgetting of every ownership answer the window has heard of: a
  // dressed card compares its baked card.ownGen against it (see refreshOwned).
  property int ownGen: waves.ownershipGeneration()
  Connections {
    target: waves
    function onOwnershipChangedBatch(batch) {
      root.ownGen = waves.ownershipGeneration()
      root.ownCardsBatch(batch)
    }
  }

  // The quality menu's own metrics, measured ONCE for the whole app: every
  // row is the same mono type, so the widest word of each column is a
  // constant and the menu can be sized to exactly the columns it shows
  // (a menu with nothing to say about the library stays as narrow as one
  // with no IN LIBRARY mark to fit).
  TextMetrics {
    id: qpmWord
    font.family: root.mono
    font.pixelSize: 10
    font.bold: true
    text: "LOSSLESS"
  }
  TextMetrics {
    id: qpmSpec
    font.family: root.mono
    font.pixelSize: 10
    text: "16/44.1"
  }
  TextMetrics {
    id: qpmNote
    font.family: root.mono
    font.pixelSize: 9
    text: "NOT OFFERED"
  }
  TextMetrics {
    id: qpmDefault
    font.family: root.mono
    font.pixelSize: 9
    text: "DEFAULT"
  }
  TextMetrics {
    id: qpmHave
    font.family: root.mono
    font.pixelSize: 9
    font.bold: true
    text: root.libraryWord
  }
  // The word a copy on disk is claimed with, the SAME rule the done face of
  // a Download button follows: with a library in the picture and downloads
  // landing inside it, "you have this" is the claim that matters; with a
  // separate download folder the honest word is DOWNLOADED.
  readonly property string libraryWord: root.libraryOn && root.dlInLibrary ? "IN LIBRARY" : "DOWNLOADED"
  // 8 margin + 6 dot + 6 + word + 6 + spec + 12 gutter + [note +6] +
  // [have +6] + 10 check + 8 margin.
  function qualMenuWidth(anyNotOffered, anyOwned) {
    return Math.ceil(46 + qpmWord.width + qpmSpec.width + (anyNotOffered ? qpmNote.width : qpmDefault.width) + 6 + (anyOwned ? qpmHave.width + 6 : 0) + 10)
  }

  // The library pill is color-coded by the QUALITY you hold, so low, middle
  // and high read at a glance: gold = hi-res, green = lossless, cyan =
  // healthy lossy, red = small lossy. "" (quality unknown) keeps the amber
  // "in library" identity. The class comes from the backend (local_class),
  // one source of truth shared with the download engine.
  // Open the library claim gate: explain the match, name the matched folder,
  // and leave DOWNLOAD ANYWAY one click away. One definition, because every
  // surface that can show a claim (the full download button, a track row's
  // button, the browse card's hover strip) has to open the SAME conversation.
  // `kind` is "album" (the default) or "track", and only picks the wording
  // and which download the ANYWAY click makes.
  function openLibraryClaim(albumId, albumTitle, folder, kind) {
    libraryClaimGate.mode = "claim"
    libraryClaimGate.card = null
    libraryClaimGate.albumId = albumId
    libraryClaimGate.albumTitle = albumTitle
    libraryClaimGate.folder = folder
    libraryClaimGate.kind = kind === "track" ? "track" : "album"
    libraryClaimGate.shown = true
  }
  // The owned twin of the claim gate, same dialog in its other mode: this
  // is a RECORD of a download Waves made, not a tag guess, so the question
  // is not "is the match right" but "fetch it again?". REDOWNLOAD forces
  // the whole job (the ownership gate would otherwise skip every track and
  // the job would fetch nothing). Takes the card so the confirm can start
  // the right kind of download (album, playlist, mix, track or video).
  // `folder` is where the recorded copy lives, when the caller knows: a copy
  // written before the download folder moved can sit anywhere, and naming
  // it is the only way the user finds it.
  function openRedownloadGate(card, folder) {
    libraryClaimGate.mode = "owned"
    libraryClaimGate.card = card
    libraryClaimGate.albumId = "" + (card.id || "")
    libraryClaimGate.albumTitle = "" + (card.title || "")
    libraryClaimGate.folder = folder ? "" + folder : ""
    libraryClaimGate.kind = (card.kind === "track" || card.kind === "video") ? "track" : "album"
    libraryClaimGate.shown = true
  }
  function pillClassFg(c) {
    return c === "hires" ? root.gold : c === "lossless" ? root.green : c === "high" ? root.cyan : c === "low" ? root.red : root.libAccent
  }
  function pillClassDim(c) {
    return c === "hires" ? root.goldDim : c === "lossless" ? root.greenDim : c === "high" ? root.cyanDim : c === "low" ? root.redDim : root.libDim
  }
  function pillClassCont(c) {
    return c === "hires" ? root.goldCont : c === "lossless" ? root.greenCont : c === "high" ? root.cyanCont : c === "low" ? root.redCont : root.libCont
  }
  function pillClassTx(c) {
    return c === "hires" ? root.goldContTx : c === "lossless" ? root.greenContTx : c === "high" ? root.cyanContTx : c === "low" ? root.redContTx : root.libContTx
  }

  // How every hover-revealed control enters and leaves: it rises from
  // below the art's bottom edge with a soft overshoot and settles, fading in
  // as it climbs, then drops back out. The fade runs on its own short curve
  // so the overshoot never dims or flickers the control. `visible` follows
  // opacity, which gates the children's MouseAreas: a control on its way out
  // can never swallow a click. Place it where the control belongs and put
  // the control inside.
  // Settings > Advanced > "Hover controls slide in". Off keeps the plain
  // fade instead, for anyone who finds the movement distracting.
  property bool hoverMotion: waves.wavesPref("hover_control_motion") !== false
  Connections {
    target: waves
    function onHoverMotionChanged() {
      root.hoverMotion = waves.wavesPref("hover_control_motion") !== false
    }
  }

  // Models. The search result rows live on each provider's own group
  // instance (SearchProviderGroup), one model set per group, so no set is
  // needed here; the rest are the queue, the artist page and
  // the library's sections.
  ListModel {
    id: queueModel
  }
  ListModel {
    id: artistAlbumsModel
  }
  ListModel {
    id: artistVideosModel
  }
  ListModel {
    id: artistEpModel
  }
  ListModel {
    id: artistTracksModel
  }
  // folder_id -> playlists remaining in its "download all" (badge digit).
  // Pane-wide: folder ids are the library's, and the badge rides the folder
  // button wherever its row renders.
  property var folderRemainMap: ({})
  // Browse category DOWNLOAD ALL flow: which tile's resolve is pending a
  // download or a preview, and the confirm prompt ({path, title, count}).
  property string catPendingDl: ""
  property string catPendingPv: ""
  property var catDlPrompt: null
  // Every way out of the bulk-download confirm that is not "Download all".
  // The tick has to go with the dialog: left armed it re-opens pre-ticked for
  // a DIFFERENT category, and confirming that one silences the confirm for
  // good, which only a full settings reset can undo.
  function catDlDismiss() {
    catDlPrompt = null
    cdSkip.checked = false
  }

  function appendPlain(model, arr) {
    if (arr)
      for (var i = 0; i < arr.length; ++i)
        model.append(arr[i])
  }
  function fill(model, arr) {
    model.clear()
    appendPlain(model, arr)
  }

  // In-place reconcile for the download queue: update existing rows by qid,
  // append new ones, drop removed, then partition into grouped order. Keeping
  // each row's delegate alive (vs fill()'s clear+rebuild) lets a status change
  // be observed in place, its completion animation fires once, and lets the
  // 5s "move to Completed" slide animate via ListView's move transition.
  function reconcileQueue(arr) {
    var m = queueModel
    arr = arr || []
    var pos = ({})
    for (var i = 0; i < m.count; ++i)
      pos[m.get(i).qid] = i
    var seen = ({})
    for (var j = 0; j < arr.length; ++j) {
      var it = arr[j]
      seen[it.qid] = true
      if (it.qid in pos) {
        var idx = pos[it.qid]
        var row = m.get(idx)
        if (row.status !== it.status)
          m.setProperty(idx, "status", it.status)
        // Wall-clock stamp of when the row finished: the root
        // lingerClock promotes on doneAt+5s whether or not the queue
        // drawer (and so this row's delegate) exists.
        if (it.status === "done" && !row.moved && !row.doneAt)
          m.setProperty(idx, "doneAt", Date.now())
        if (row.progress !== it.progress)
          m.setProperty(idx, "progress", it.progress)
        if (row.name !== it.name)
          m.setProperty(idx, "name", it.name)
        // Why a settled row ended the way it did. Patched here as well
        // as in queueRowPatch, because this is a SEPARATE writer: a
        // resync is what a rebuild and a big STOP deliver, and a field
        // only the delta path carries is stale for every row a resync
        // touches.
        var rsn = it.reason || ""
        if (row.reason !== rsn)
          m.setProperty(idx, "reason", rsn)
        if (row.artist !== it.artist)
          m.setProperty(idx, "artist", it.artist || "")
        if (row.tracks !== it.tracks)
          m.setProperty(idx, "tracks", it.tracks || 0)
        var q = it.quality || ""
        if (row.quality !== q)
          m.setProperty(idx, "quality", q)
        var ex = it.expected || ""
        if (row.expected !== ex)
          m.setProperty(idx, "expected", ex)
        // What the files landed at, rolled up by the bridge from its
        // per-track registry, so a COLLAPSED row states the delivery.
        var ld = it.landed || ""
        if (row.landed !== ld)
          m.setProperty(idx, "landed", ld)
        // Per-tier counts as a JSON string, not a list: a ListModel
        // role given a JS array turns it into a nested ListModel, and
        // the delegate wants the array back. A string role also gives
        // the badge a stable value to bind against, so it rebuilds when
        // the mix really changes and not on every tick. The bridge
        // pre-serializes it (mixJson) once per change; the stringify
        // fallback covers rows built by labs and tests.
        var mx = it.mixJson || JSON.stringify(it.mix || [])
        if (row.mixJson !== mx)
          m.setProperty(idx, "mixJson", mx)
        // Keep a row that has already moved to Completed there; otherwise
        // group by status: failed rows and the rows STOP ended each get
        // their own section (both with a RETRY ALL header), queued rows
        // theirs, the rest ride Downloading.
        var grp = row.moved ? "completed" : root.groupForStatus(it.status)
        if (row.uiGroup !== grp)
          m.setProperty(idx, "uiGroup", grp)
      } else {
        // Every role the drawer reads, named in one place (see
        // queueRowObject for why that matters).
        m.append(queueRowObject(it))
      }
    }
    // A row that has left the queue takes its per-qid state with it: the
    // expanded track list AND the expansion flag itself. Live ticks update
    // queueTracks in place, but an entry outliving its row is still a
    // leak a session of finished albums would grow forever; queueExpanded
    // is the same row's state. One copy of each for the whole sweep (drops
    // are rare), not one per row.
    var dropped = []
    for (var k = m.count - 1; k >= 0; --k) {
      var gone = m.get(k).qid
      if (!seen[gone]) {
        dropped.push(gone)
        m.remove(k)
      }
    }
    if (dropped.length > 0) {
      var tracks = Object.assign({}, root.queueTracks), forgot = false
      var exp = Object.assign({}, root.queueExpanded), collapsed = false
      for (var d = 0; d < dropped.length; ++d) {
        if (tracks[dropped[d]] !== undefined) {
          delete tracks[dropped[d]]
          forgot = true
        }
        if (exp[dropped[d]] !== undefined) {
          delete exp[dropped[d]]
          collapsed = true
        }
      }
      if (forgot)
        root.queueTracks = tracks
      if (collapsed)
        root.queueExpanded = exp
    }
    queuePartition()
    updateQueueCounts()
  }

  // Stable-partition the queue model into [completed, failed, stopped,
  // downloading, queued], preserving each group's internal order. Only emits
  // move()s when something is out of place (so a steady queue animates
  // nothing). Failed and Stopped sit above the active groups so retries are
  // in reach, below Completed so the drawer still opens on the familiar
  // collapsed header; Failed first because a failure wants the eye before
  // something the user ended on purpose.
  function queuePartition() {
    var m = queueModel, w = 0, order = ["completed", "failed", "stopped", "downloading", "queued"]
    for (var g = 0; g < order.length; ++g) {
      for (var i = w; i < m.count; ++i) {
        if (m.get(i).uiGroup === order[g]) {
          if (i !== w)
            m.move(i, w, 1)
          w++
        }
      }
    }
  }

  // qid -> model row, rebuilt in the pass that recounts the groups (every
  // structural change already ends in one, so the map costs nothing extra).
  // See queueRowIndexOf for why it exists.
  property var queueRowIndex: ({})
  // The inverse: the qid at each model index. Mutated in place, never
  // bound. A move or removal shifts a run of rows, and this is how their
  // index entries are corrected without asking the model for each row.
  property var qidAt: []
  // Finished rows waiting for their 5s linger (status done, not yet moved
  // to Completed): the linger clock reads these, not the whole model.
  property var lingerQids: []

  function updateQueueCounts() {
    var m = queueModel, c = 0, f = 0, s = 0, d = 0, q = 0, a = 0, idx = ({}), at = [], ling = []
    for (var i = 0; i < m.count; ++i) {
      var row = m.get(i)
      idx[row.qid] = i
      at.push(row.qid)
      var grp = row.uiGroup
      if (grp === "completed")
        c++
      else if (grp === "failed")
        f++
      else if (grp === "stopped")
        s++
      else if (grp === "downloading")
        d++
      else
        q++
      if (row.status === "done" && !row.moved)
        ling.push(row.qid)
      if (row.status === "queued" || row.status === "running")
        a++
    }
    root.queueRowIndex = idx
    root.qidAt = at
    root.lingerQids = ling
    root.completedCount = c
    root.failedCount = f
    root.stoppedCount = s
    root.downloadingCount = d
    root.queuedCount = q
    root.lingerCount = ling.length
    root.activeQueueCount = a
  }

  // delta bookkeeping
  // The bridge reports what changed (rows added, rows whose fields moved,
  // rows gone) and these apply it in place: the cost is the rows named,
  // never a walk of the model. queueChanged (the whole queue) still lands
  // in reconcileQueue for a full resync.
  function queueGroupCount(grp) {
    return grp === "completed" ? root.completedCount : grp === "failed" ? root.failedCount : grp === "stopped" ? root.stoppedCount : grp === "downloading" ? root.downloadingCount : root.queuedCount
  }
  function queueGroupBump(grp, d) {
    if (grp === "completed")
      root.completedCount += d
    else if (grp === "failed")
      root.failedCount += d
    else if (grp === "stopped")
      root.stoppedCount += d
    else if (grp === "downloading")
      root.downloadingCount += d
    else
      root.queuedCount += d
    // The one funnel every section count passes through, so it is where
    // the header pulse is named: the section that GREW. A promotion bumps
    // two sections in the same tick, one down and one up, and only the
    // rise is news.
    if (d > 0) {
      root.pulseSection = grp
      root.pulseTick += 1
    }
  }
  // Model index where a group begins: the groups sit in a fixed order and
  // each is contiguous, so a boundary is a sum of counts.
  function queueGroupStart(grp) {
    var s = 0
    if (grp === "completed")
      return 0
    s += root.completedCount
    if (grp === "failed")
      return s
    s += root.failedCount
    if (grp === "stopped")
      return s
    s += root.stoppedCount
    if (grp === "downloading")
      return s
    return s + root.downloadingCount
  }
  // Re-point the index entries of model rows lo..hi after a shift.
  function queueIndexFix(lo, hi) {
    var at = root.qidAt, idx = root.queueRowIndex
    for (var k = Math.max(0, lo); k <= hi; ++k)
      idx[at[k]] = k
  }
  function queueModelMove(from, to) {
    if (from === to)
      return
    queueModel.move(from, to, 1)
    var at = root.qidAt, q = at.splice(from, 1)[0]
    at.splice(to, 0, q)
    queueIndexFix(Math.min(from, to), Math.max(from, to))
  }
  function queueActiveStatus(st) {
    return st === "queued" || st === "running"
  }
  function queueLingerAdd(qid) {
    if (root.lingerQids.indexOf(qid) < 0) {
      root.lingerQids.push(qid)
      root.lingerCount = root.lingerQids.length
    }
  }
  function queueLingerDrop(qid) {
    var k = root.lingerQids.indexOf(qid)
    if (k >= 0) {
      root.lingerQids.splice(k, 1)
      root.lingerCount = root.lingerQids.length
    }
  }
  // The row object the model holds for a bridge row. EVERY field the drawer
  // reads has to be named here, including ones that are empty on arrival:
  // a ListModel fixes its roles from the first object appended, so a role
  // missing here does not exist on any row, reads as undefined in the
  // delegate, and fails silently (no warning, no binding error). `quality`
  // was exactly that: the bridge set it on every row and the drawer never
  // saw one, so a queued row could not state its tier.
  function queueRowObject(it) {
    return {
      qid: it.qid,
      name: it.name,
      type: it.type,
      status: it.status,
      reason: it.reason || "",
      progress: it.progress,
      media_id: it.media_id,
      template: it.template,
      collection: it.collection,
      artist: it.artist || "",
      tracks: it.tracks || 0,
      art: it.art || "",
      quality: it.quality || "",
      expected: it.expected || "",
      landed: it.landed || "",
      mixJson: it.mixJson || JSON.stringify(it.mix || []),
      quarantineCount: it.quarantineCount || 0,
      uiGroup: root.groupForStatus(it.status),
      moved: false,
      doneAt: (it.status === "done" ? Date.now() : 0),
      leaving: false
    }
  }
  // A row the bridge appended: it joins the end of its group (a queued row,
  // the usual case, is the end of the model, so this is an append).
  function queueRowAdd(it) {
    var m = queueModel, row = queueRowObject(it), grp = row.uiGroup
    var at = queueGroupStart(grp) + queueGroupCount(grp)
    if (at >= m.count) {
      m.append(row)
      root.qidAt.push(row.qid)
      root.queueRowIndex[row.qid] = m.count - 1
    } else {
      m.insert(at, row)
      root.qidAt.splice(at, 0, row.qid)
      queueIndexFix(at, m.count - 1)
    }
    queueGroupBump(grp, 1)
    if (queueActiveStatus(row.status))
      root.activeQueueCount += 1
    if (row.status === "done")
      queueLingerAdd(row.qid)
  }
  // A row whose fields changed: the same field-by-field update the full
  // reconcile does, then a move to its new group's end if the group moved.
  function queueRowPatch(it) {
    var m = queueModel, i = root.queueRowIndexOf(it.qid)
    if (i < 0) {
      queueRowAdd(it)
      return
    }
    var row = m.get(i)
    var was = row.status, wasGrp = row.uiGroup
    if (was !== it.status) {
      m.setProperty(i, "status", it.status)
      if (queueActiveStatus(was) !== queueActiveStatus(it.status))
        root.activeQueueCount += queueActiveStatus(it.status) ? 1 : -1
    }
    // Wall-clock stamp of when the row finished: the root lingerClock
    // promotes on doneAt+5s whether or not the queue drawer (and so this
    // row's delegate) exists.
    if (it.status === "done" && !row.moved && !row.doneAt) {
      m.setProperty(i, "doneAt", Date.now())
      queueLingerAdd(it.qid)
    }
    var rsn = it.reason || ""
    if (row.reason !== rsn)
      m.setProperty(i, "reason", rsn)
    if (row.progress !== it.progress)
      m.setProperty(i, "progress", it.progress)
    if (row.name !== it.name)
      m.setProperty(i, "name", it.name)
    if (row.artist !== it.artist)
      m.setProperty(i, "artist", it.artist || "")
    if (row.tracks !== it.tracks)
      m.setProperty(i, "tracks", it.tracks || 0)
    var qv = it.quality || ""
    if (row.quality !== qv)
      m.setProperty(i, "quality", qv)
    var ex = it.expected || ""
    if (row.expected !== ex)
      m.setProperty(i, "expected", ex)
    var ld = it.landed || ""
    if (row.landed !== ld)
      m.setProperty(i, "landed", ld)
    var mx = it.mixJson || JSON.stringify(it.mix || [])
    if (row.mixJson !== mx)
      m.setProperty(i, "mixJson", mx)
    var qc = it.quarantineCount || 0
    if (row.quarantineCount !== qc)
      m.setProperty(i, "quarantineCount", qc)
    var grp = row.moved ? "completed" : root.groupForStatus(it.status)
    if (grp === wasGrp)
      return
    m.setProperty(i, "uiGroup", grp)
    // Leave the old group, land at the end of the new one: the position
    // the stable partition would have given it.
    // (Counts without this row give the index it lands on, which is what
    // ListModel.move takes: the item's index after the move.)
    queueGroupBump(wasGrp, -1)
    var to = queueGroupStart(grp) + queueGroupCount(grp)
    queueGroupBump(grp, 1)
    queueModelMove(i, to)
  }
  // Rows gone from the bridge: removed highest index first (so the lower
  // ones stay valid), then one pass re-points the rows that shifted.
  function queueRowsDrop(qids) {
    var m = queueModel, idxs = [], lo = m.count
    for (var n = 0; n < qids.length; ++n) {
      var i = root.queueRowIndexOf(qids[n])
      if (i >= 0)
        idxs.push(i)
    }
    if (idxs.length === 0)
      return
    idxs.sort(function (a, b) {
      return b - a
    })
    var tracks = null, exp = null
    for (var k = 0; k < idxs.length; ++k) {
      var at = idxs[k], row = m.get(at), qid = row.qid
      queueGroupBump(row.uiGroup, -1)
      if (queueActiveStatus(row.status))
        root.activeQueueCount -= 1
      if (row.status === "done" && !row.moved)
        queueLingerDrop(qid)
      // A row that has left the queue takes its per-qid state with it:
      // the expanded track list AND the expansion flag itself (see
      // reconcileQueue). One copy of each for the whole sweep.
      if (root.queueTracks[qid] !== undefined) {
        if (!tracks)
          tracks = Object.assign({}, root.queueTracks)
        delete tracks[qid]
      }
      if (root.queueExpanded[qid] !== undefined) {
        if (!exp)
          exp = Object.assign({}, root.queueExpanded)
        delete exp[qid]
      }
      m.remove(at)
      root.qidAt.splice(at, 1)
      delete root.queueRowIndex[qid]
      if (at < lo)
        lo = at
    }
    if (tracks)
      root.queueTracks = tracks
    if (exp)
      root.queueExpanded = exp
    queueIndexFix(lo, m.count - 1)
  }

  // The statuses a row's RETRY applies to: a failure, and a row STOP ended.
  // Mirrors the bridge's _RETRYABLE. The two live in separate sections, so
  // each header's RETRY ALL takes one of them, not both.
  function retryableStatus(st) {
    return st === "failed" || st === "cancelled"
  }

  // Which drawer section a row of this status files under (a row already
  // moved to Completed stays there regardless; see reconcileQueue).
  function groupForStatus(st) {
    return st === "failed" ? "failed" : st === "cancelled" ? "stopped" : st === "queued" ? "queued" : "downloading"
  }

  // The model row holding a qid, without walking the model to find it.
  // Progress ticks arrive per delivered segment, dozens a second per active
  // download; scanning every row per tick would run on the GUI thread
  // thousands of times a second with a few hundred rows, which makes a long
  // batch feel heavy. The map above is rebuilt after every structural change;
  // a tick landing between a move and that rebuild pays for one rebuild
  // here, not a scan. -1 means the row is gone, which a late tick for a
  // cancelled job will see.
  function queueRowIndexOf(qid) {
    var i = root.queueRowIndex[qid]
    if (i !== undefined && i < queueModel.count && queueModel.get(i).qid === qid)
      return i
    updateQueueCounts()
    i = root.queueRowIndex[qid]
    return (i === undefined) ? -1 : i
  }

  // The linger clock: finished rows fold into Completed on a wall clock
  // (doneAt + 5s), whether or not the queue drawer is open. Pinning this
  // timing to the per-row delegate would stop it with the drawer closed
  // (no delegate is there to run it), and opening the drawer after a big
  // batch would animate every row at once. Rows on screen still get the
  // leaving fade first; with the drawer closed the promotion is silent
  // (there is nothing to animate).
  Timer {
    id: lingerClock
    interval: 1000
    repeat: true
    running: root.lingerCount > 0
    onTriggered: {
      // Only the rows waiting to fold, not the whole model: with a long
      // backlog behind them a per-second walk of every row was a steady
      // drain on the GUI thread for as long as anything was finishing.
      var m = queueModel, now = Date.now(), waiting = root.lingerQids.slice()
      for (var k = 0; k < waiting.length; ++k) {
        var i = root.queueRowIndexOf(waiting[k])
        if (i < 0) {
          queueLingerDrop(waiting[k])
          continue
        }
        var row = m.get(i)
        if (row.status !== "done" || row.moved) {
          queueLingerDrop(waiting[k])
          continue
        }
        if (!row.doneAt) {
          m.setProperty(i, "doneAt", now)
          continue
        }
        var age = now - row.doneAt
        if (age < 5000)
          continue
        if (!queueDrawer.visible) {
          promoteCompleted(row.qid)
          continue
        }
        // Visible: fade the row out (leaving), then move it once the
        // fade has finished (next tick).
        if (!row.leaving)
          m.setProperty(i, "leaving", true)
        else if (age >= 5500)
          promoteCompleted(row.qid)
      }
    }
  }

  // Move a finished row into the Completed group (after its 5s linger). It
  // slides to the top of Completed via the ListView move transition.
  function promoteCompleted(qid) {
    var m = queueModel
    // Indexed, not searched: the linger clock promotes every row of a
    // finished batch, and a scan apiece made that whole sweep cost the
    // square of the batch.
    var i = root.queueRowIndexOf(qid)
    if (i < 0 || m.get(i).uiGroup === "completed")
      return
    // Land at the TOP of the Completed group (newest first, oldest at the
    // bottom); Completed is the first group, so that is model index 0. The
    // ListView move transition slides it up.
    var wasGrp = m.get(i).uiGroup
    m.setProperty(i, "moved", true)
    m.setProperty(i, "uiGroup", "completed")
    m.setProperty(i, "leaving", false)
    queueGroupBump(wasGrp, -1)
    queueGroupBump("completed", 1)
    queueLingerDrop(qid)
    queueModelMove(i, 0)
  }

  // Media rows carry an `artists` array (clickable per-artist); ListModel
  // doesn't handle nested arrays well, so stash them in a side map by id.
  function appendMedia(model, arr) {
    var m = root.artistsById
    if (arr)
      for (var i = 0; i < arr.length; ++i) {
        var it = arr[i]
        if (it.artists)
          m[it.id] = it.artists
        var copy = {}
        for (var k in it)
          if (k !== "artists")
            copy[k] = it[k]
        model.append(copy)
      }
    root.artistsById = m
  }
  function fillMedia(model, arr) {
    model.clear()
    appendMedia(model, arr)
  }

  // In-place refill keyed by id, for the search page's stale-then-refresh.
  //
  // fill() clears and rebuilds, which destroys and recreates every delegate.
  // The refresh path deliberately runs with searchBuilding false (no veil,
  // no loading flash, the page the user is reading just becomes current), and
  // the Loaders read that same flag for their asynchronous property, so every
  // one of those rebuilds happens SYNCHRONOUSLY on the GUI thread. A full
  // result set measured 272 to 316ms of frozen window against 13 to 14ms for
  // the fresh handler, on the one path whose whole purpose was to feel
  // instant. A refresh normally differs by a row or two, so almost every
  // delegate here is kept and only the fields that really changed are
  // written. Rows are matched by id, so a row that merely MOVED is moved
  // rather than rebuilt.
  //
  // ``media`` mirrors appendMedia: the artists list is lifted out of the row
  // into artistsById rather than stored as a nested ListModel.
  function reconcileById(model, arr, media) {
    arr = arr || []
    var m = media ? Object.assign({}, root.artistsById) : null
    for (var j = 0; j < arr.length; ++j) {
      var it = arr[j]
      var row = {}
      for (var k in it)
        if (!media || k !== "artists")
          row[k] = it[k]
      if (media && it.artists)
        m[it.id] = it.artists
      var at = -1
      for (var i = j; i < model.count; ++i)
        if (model.get(i).id === it.id) {
          at = i
          break
        }
      if (at < 0) {
        model.insert(j, row)
        continue
      }
      if (at !== j)
        model.move(at, j, 1)
      var cur = model.get(j)
      for (var f in row)
        if (cur[f] !== row[f])
          model.setProperty(j, f, row[f])
    }
    if (model.count > arr.length)
      model.remove(arr.length, model.count - arr.length)
    // A fresh object, never the same reference back: assigning artistsById
    // to itself notifies nothing, and with the rows no longer rebuilt there
    // is nothing else to make a stale credit list correct itself.
    if (media)
      root.artistsById = m
  }

  // My Music sort options (per category). Options adapt to the category;
  // every category shares a "Recently added" default so it matches the
  // backend's default order with no extra fetch. The per-source groups hold
  // the chosen value (see LibSourceGroup.sortGet/applySort).
  function libSortOptions(cat) {
    if (cat === "albums")
      return [["Recently added", "date"], ["Name", "name"], ["Release date", "release"], ["Artist", "artist"]]
    if (cat === "tracks" || cat === "videos")
      return [["Recently added", "date"], ["Name", "name"], ["Artist", "artist"]]
    return [["Recently added", "date"], ["Name", "name"]]
    // artists, playlists, mixes
  }
  function libSortLabels(cat) {
    return root.libSortOptions(cat).map(function (o) {
      return o[0]
    })
  }
  // From a Home "Recently added" preview shelf, open the full list of that
  // kind on the shelf's OWN source, forced to newest-first so it lands on the
  // very items the preview showed and the complete list beneath them. The
  // section carries its source (the bridge composes it), so with two sources
  // the heading opens the shelf it came from, never the first group's.
  function openLibrarySorted(source, cat) {
    if (!cat)
      return
    var g = root.libGroupFor(source)
    if (g)
      g.selectSorted(String(cat))
  }
  // The empty state's click: the provider's own sign-in steps where this
  // build ships them, its own setup verb otherwise. The action is a verb
  // from the bridge, never a provider branch here.
  function runMyMusicEmptyAction() {
    var empty = root.myMusicEmpty || ({})
    var provider = String(empty.provider || "")
    if (!provider)
      return
    // The provider's own verb, dispatched through the bridge: a session
    // provider's sign-in comes back as signInRequested and opens the
    // surface on the steps this build ships for it. No verb branch here.
    waves.providerAction(provider, String(empty.action || ""))
  }
  // The providers whose sign-in the welcome surface's inline steps complete
  // (the bridge's wiring; the steps are QML components, see
  // waves.providerSignInSteps). A provider without one lands on the cards,
  // where its own card action lives, rather than a blank page.
  property var signInStepProviders: []
  function openProviderSignIn(providerId) {
    openSetupPage()
    var id = String(providerId || "")
    setupMode = root.signInStepProviders.indexOf(id) >= 0 ? id : "cards"
  }
  // The account flipped: every keep-alive My Music pane holds the previous
  // account's rows for its whole life, so the flip is the one thing that
  // clears them (per source group, each of which owns its own models).
  function clearMyMusicPanes() {
    var groups = root.libGroupList()
    for (var i = 0; i < groups.length; ++i)
      groups[i].clearPanes()
    // No category reset: the pane stays where the user left it, and the
    // primary group's mirror keeps root.libraryCategory in step.
  }

  Connections {
    target: waves
    function onAppleStatusChanged() {
      // The chip's "can any provider download yet" test and Apple's
      // search-group clearing both read the same fresh light.
      root.appleLight = waves.appleStatus()
      root.refreshProviderSurfaces()
      if (waves.appleStatus().state === "off")
        root.clearSearchGroup("apple")
    }
    function onSetupRequested() {
      root.openSetupPage()
    }
    function onAppleSetupRequested(reason) {
      root.openAppleSetup(reason)
    }
    // Every My Music emit names its SOURCE: the group for
    // that source applies the page, so two sources' panes fill
    // independently and a closed source's late answer lands nowhere.
    function onLibraryLoaded(source, cat, items, more) {
      var g = root.libGroupFor(source)
      if (g)
        g.applyLoaded(cat, items, more)
    }
    function onLibraryMore(source, cat, items, more) {
      var g = root.libGroupFor(source)
      if (g)
        g.applyMore(cat, items, more)
    }
    // The Library section's pages (ADR 0007): provider-free,
    // so they land on the section itself, not on a source group.
    function onLibraryFilesLoaded(view, items, more, total) {
      libSection.applyLoaded(view, items, more, total)
    }
    function onLibraryFilesMore(view, items, more, total) {
      libSection.applyMore(view, items, more)
    }
    function onPlaylistFolderLoaded(source, fid, rows, path) {
      var g = root.libGroupFor(source)
      if (g)
        g.applyFolder(fid, rows, path)
    }
    function onFolderRemaining(fid, remaining, total) {
      // New object on purpose: mutate-and-reassign doesn't notify.
      var m = Object.assign({}, root.folderRemainMap)
      m[fid] = remaining
      root.folderRemainMap = m
    }
    // A Browse category finished resolving (count known, list cached):
    // run whichever action the user queued on the tile.
    function onPlaylistCategoryResolved(path, title, count, firstId) {
      if (root.catPendingPv === path) {
        root.catPendingPv = ""
        if (firstId !== "")
          root.togglePreview("playlist", firstId, 0)
      }
      if (root.catPendingDl !== path)
        return
      root.catPendingDl = ""
      if (count <= 0)
        // backend already set the status line
        return
      if (waves.confirmCategoryDl)
        root.catDlPrompt = {
          path: path,
          title: title || "this category",
          count: count
        }
      else
        waves.downloadPlaylistCategory(path)
    }
    function onHomeLoaded(source, sections) {
      var g = root.libGroupFor(source)
      if (g)
        g.applyHome(sections)
    }
    function onDownloadFolderMissing() {
      root.folderGateBlocking = true
    }
    function onDownloadFolderDefault() {
      root.folderNudge = true
    }
    function onDownloadFolderUnreachable(path) {
      root.folderUnreachablePath = path
      root.folderUnreachable = true
    }
    // The recovery watch saw the drive come back and already resumed the
    // held downloads: the gate dialog closes itself.
    function onDownloadFolderRecovered() {
      root.folderUnreachable = false
    }
    function onFfmpegMissingBlocked() {
      root.ffmpegBlocked = true
    }
    function onLoggedInChanged() {
      // The header's lights follow the session, and so does Browse's
      // answer: the TIDAL mark flips with the flag every catalog read
      // moves with, and the landing's call to action retires with it.
      // The welcome's cards follow the same flips.
      root.refreshProviderSurfaces()
      root.refreshBrowseNav()
      // Drop every QML-side copy of Browse data when the account flips:
      // the landing embeds personalized For You rows, and the backend's
      // own logout cache-clear can't reach these copies. Re-fetch right
      // away if the user is sitting on the Browse tab.
      root.browseSections = []
      root.browseChips = {
        genres: [],
        moods: [],
        decades: []
      }
      root.browsePage = null
      root.browsePageKey = ""
      root.browseTitleHint = ""
      root.browseArtHint = ""
      root.browseStack = []
      root.browseError = false
      root.browsePageError = false
      root.browsePageLoading = false
      root.browseLoading = false
      // Including a landing payload parked mid-handover: it is the
      // previous account's, and applying it after the reveal would put
      // their personalized rows back on screen.
      root._browseParked = null
      // History snapshots hold page payloads (personalized rows) and
      // artist ids from the previous account, drop them too (both
      // stacks: a stale forward entry would otherwise replay the old
      // account's page when the forward button is pressed).
      root.navHistory = []
      root.navForwardHistory = []
      root._navRestoring = false
      root.browseHighlightId = ""
      // A DOWNLOAD ALL or PREVIEW whose resolve the logout generation
      // bump threw away is still armed here. Left alone, the next resolve
      // of the same category path after signing back in consumes it: a
      // confirm nobody asked for, or (with the confirm muted) the whole
      // category queued on the new account off a click made on the old.
      root.catPendingDl = ""
      root.catPendingPv = ""
      root.catDlPrompt = null
      // The keep-alive My Music panes hold the previous account's
      // favourites for their whole life; only the account flip may
      // clear them (switching categories never does).
      root.clearMyMusicPanes()
      // The saved Search drill-in can hold the previous account's artist
      // page, restorable from the Search tab: same class of leak as the
      // history stacks dropped above.
      root.searchSaved = null
      // The folder badges are the previous account's too.
      root.folderRemainMap = ({})
      if (root.signedIn && root.browseOpen) {
        root.browseLoading = true
        waves.loadBrowse()
      }
      // A sign-in that lands while the welcome surface is on its TIDAL
      // steps is finished there: close it and land on Search.
      if (root.signedIn)
        root.finishSetupSignIn()
    }
    function onBrowseLoaded(p) {
      root.markRender("browse render")
      root.browseLoading = false
      // The handover is the reveal itself: the wordmark zooming out and
      // the interface fading up over ~1.4s. bootOverlay.done is still
      // false throughout, so a revalidate landing in that window would
      // take the fresh-build path, raise the veil and blank the landing
      // under the fade. That is precisely the "watched the page assemble
      // itself" symptom the launch hold exists to prevent, and it is
      // reachable because the second build runs asynchronously.
      // Park it and apply it on the other side, where it is an ordinary
      // in-place refresh. Only a landing that already has content can
      // wait: a first build has nothing to reveal and must go through.
      // The window spans the whole visible handover: the version drain
      // (bootBlk) and the zoom/reveal (bootZoom), which the drain's
      // last tick starts.
      if ((bootHandover.running || bootBlk.running || bootZoom.running) && root.browseSections.length > 0) {
        root._browseParked = p
        return
      }
      // The first build has the mirror problem at the other end of the
      // boot: on a warm cache the payload lands ~1.5s in, mid wordmark
      // fade (bootIntro), and even the async build's section shells cost
      // a real frame gap, so the fade visibly hitches. Park it until the
      // fade completes; bootIntro's
      // onFinished applies it, still a good second clear of the
      // handover's incubation wait, so the reveal is not delayed. An
      // error payload goes straight through: it has no sections to
      // build, and the boot's error path must not sit on the wordmark.
      if (bootIntro.running && !p.error && root.browseSections.length === 0) {
        root._browseParked = p
        return
      }
      root.applyBrowseLanding(p)
    }
    // A hovered page is built: pull its covers into the warm pool at
    // the exact sizes the page will ask for (hero Art decodeW 360, the
    // 480 backdrop, the 68 px PreviewArt discs of the first rows), so
    // the click paints them from the pixmap cache. A screenful at most,
    // against the pool's 220 entries; warmArt dedupes.
    function onBrowsePagePrefetched(p) {
      if (p.art) {
        root.warmArt("" + p.art, 360, 360)
        root.warmArt("" + p.art, 480, 480)
      }
      var arts = p.rowArts || []
      for (var i = 0; i < arts.length && i < 16; ++i)
        root.warmArt("" + arts[i], root.discDecode, root.discDecode)
    }
    function onBrowsePageLoaded(p) {
      if (p.key !== root.browsePageKey)
        // stale: user already left this page
        return
      root.markRender("browse page render")
      root.browsePageLoading = false
      root.browsePageError = !!p.error
      root.browseArtistsSideMap(p.sections || [])
      // Opening an album ON a track: arm the hide BEFORE assigning the page,
      // so its rows lay out already invisible (browseCol opacity 0) and never
      // paint at the top for a frame before the highlighted row centers
      // itself. The row's own timer then scrolls into place and reveals;
      // hiRevealGuard (re-armed by this pending change) clears the hide if the
      // row never appears. Without this the pane flashed the top then scrolled
      // for an uncached album, e.g. one opened from a My Music Home shelf.
      if (!p.error && root.browseHighlightId !== "")
        root.browseHighlightPending = true
      // A revalidate re-emit of the page already showing swaps it in
      // place; hold the user's spot across the rebuild (see holdScroll).
      if (root.browsePage && !p.error)
        browseDrill.holdScroll()
      root.browsePage = p.error ? null : p
      // Whether this TIDAL album is already in the user's local library is
      // resolved by onBrowsePageChanged above, which covers every way a
      // page can arrive. Re-resolve here too for the one case that is not
      // a change: a revalidate re-emitting the SAME page object.
      root._resolveLibraryPresence()
    }
    // The local library-presence index (re)built: re-query for the album on
    // screen so the badge appears/updates with no reload.
    function onLibraryPresenceChanged() {
      root.libStamp = waves.libraryStamp()
      root._resolveLibraryPresence()
      // The Library section's file lists are the scan's own: a publish
      // can have added, retagged or pruned rows, so the visible view
      // reloads, and a hidden pane is marked stale so returning to it
      // refreshes (a no-op on an unconfigured section).
      if (root.libraryOpen)
        libSection.reload()
      else
        libSection.invalidate()
      // A search page waiting behind the veil for its badges can have
      // them now. Handed to a zero-interval timer rather than revealed
      // here: this handler belongs to a Connections created when the
      // engine loaded, and every badge's own Connections was created
      // later, inside a delegate. Qt delivers in connection order, so
      // revealing on this line dropped the veil BEFORE a single pill had
      // re-resolved, and the badges then faded in over the page they had
      // just been held back for. One event-loop pass puts the whole page
      // behind the reveal, which is the point of waiting at all.
      if (root._searchAwaitingLibrary)
        searchLibraryReveal.restart()
    }
    function onBrowseSectionMore(p) {
      root.browseGrew(p)
    }
    function onVideoReady(p) {
      // Stale resolve (overlay closed, or another video opened since).
      if (!root.videoNow || ("" + p.id) !== root.videoNow.id)
        return
      if (p.error) {
        if (root.videoSwitching) {
          root.videoSwitching = false
          return
        }  // keep the old stream playing
        // Same for a promotion: the adopted peek keeps playing, just
        // at glance resolution, and the user sees no failure at all.
        if (root.videoUpgrading) {
          root._videoUpgradeGiveUp()
          return
        }
        root.videoLoading = false
        root.videoError = true
        return
      }
      if (root.videoSwitching) {
        // Seamless-as-possible swap: freeze the current frame over the
        // surface (the source change blanks the VideoOutput), swap,
        // then resume at the captured position once the new stream is
        // seekable (applyVideoSeek retries until it is).
        root.videoSwitching = false
        root.videoNow = Object.assign({}, root.videoNow, {
          res: p.res || 0,
          heights: p.heights || []
        })
        var swapUrl = p.url
        videoStage.grabToImage(function (result) {
          root._videoGrab = result
          // keep alive while displayed
          videoFreeze.source = result.url
          videoFreeze.visible = true
          root.videoPendingSeek = videoPlayer.position
          root._videoSeekTries = 0
          videoPlayer.source = swapUrl
          videoPlayer.play()
          videoSeekRetry.restart()
        })
        return
      }
      root.videoNow = {
        id: root.videoNow.id,
        title: p.title || root.videoNow.title,
        artist: p.artist || root.videoNow.artist,
        artists: p.artists || [],
        albumId: p.album_id || "",
        trackId: p.track_id || "",
        res: p.res || 0,
        heights: p.heights || []
      }
      root.videoLoading = false
      if (root.videoUpgrading) {
        // Promotion upgrade: the adopted peek is on stage and
        // sounding, so the real stream starts MUTED on the off-stage
        // sink and chases its clock (videoUpgradeRetry cuts across
        // once they line up). Nothing visible happens until then.
        videoOut.muted = true
        root._videoUpTries = 0
        root._videoUpAims = 0
        root._videoUpPhase = 0
        root._videoUpTarget = -1
        videoPlayer.source = p.url
        videoPlayer.play()
        videoUpgradeRetry.restart()
        return
      }
      videoPlayer.source = p.url
      videoPlayer.play()
    }
    function onVideoPeekReady(p) {
      // Stale resolve: the card closed, or retargeted to another video.
      if (!root.peekNow || ("" + p.id) !== root.peekNow.id)
        return
      if (p.error) {
        root.peekClose()
        return
      }
      peekPlayer.source = p.url
      peekPlayer.play()
    }
    function onBrowseTileArt(path, arts) {
      // Mutate the buffer in place (no rebind) and coalesce via the timer.
      root._tileArtPending[path] = arts
      tileArtFlush.restart()
    }
    function onSearchResults(r) {
      // A search resolves over seconds (paginated fan-out), so its
      // results can land AFTER the user clicked an artist or album name
      // and left. Rendering then would yank them to the search page as
      // if their click had searched. Accept only when nothing was
      // navigated since the search was issued (_searchSeq snapshot) and
      // no other surface took over meanwhile (card clicks flip these
      // flags without a markNav; artistOpen is deliberately allowed,
      // the search tier is live on artist pages). Dropped payloads stay
      // in the backend's search cache, re-searching is instant.
      if (root._searchSeq !== root._navSeq || root.browseOpen || root.libraryOpen || root.settingsOpen)
        return
      var groups = r.groups || []
      if (r.refresh) {
        // The wire's answer to a search painted from an older result
        // (the backend's stale-then-revalidate, see search()): the
        // rows swap in place and nothing else moves. No history
        // entry, no scroll reset, no build veil, no cache reset: the
        // page the user is already reading just becomes current.
        // Only the groups already on the page refresh; a refresh can
        // neither mount nor unmount a provider.
        root.applySearchGroups(groups, true)
        root.registerPinnedArtists()
        root.searchNoResultsFor = ""
        return
      }
      root.navPush()
      root.markRender("search render")
      root.searchSaved = null
      // a fresh search replaces the saved drill-in
      // A fresh search always lands at the top. The page keeps one
      // scroll position for every section (the sections stack inside
      // the one results Flickable), so without this the new results
      // render at the old search's scroll offset. The artist strips
      // keep their own horizontal offsets, reset alongside.
      results.contentY = 0
      for (var stripIndex = 0; stripIndex < searchGroupRep.count; ++stripIndex) {
        var stripGroup = searchGroupRep.itemAt(stripIndex)
        if (stripGroup)
          stripGroup.resetStripOffset()
      }
      root.navOrigin = "search"
      root.browseOpen = false
      root.artistOpen = false
      root.libraryOpen = false
      root.trackCache = ({})
      root.resetExpandedAlbums({})
      // Playlist rows expand the same way, and their cache has to go with
      // them: playlists mutate, so a row left expanded across searches
      // would show yesterday's tracks with no refetch to correct them.
      root.playlistTrackCache = ({})
      root.expandedPlaylists = ({})
      // The type chip is a filter on ONE set of results, not a mode: left
      // sticky, an earlier Albums click hid the ARTISTS section of every
      // later search (an artist could not be found at all). Reset here,
      // where new results land, so it also covers cache-served searches.
      root.filterType = "all"
      // A section a user expanded stays expanded on the next search (the
      // groups' pref-backed flags), so nothing is reset here.
      // Arm the build veil BEFORE the groups fill: the Loaders each
      // delegate creates read searchBuilding for their asynchronous
      // flag, and the ready ticks only ever arrive on later frames,
      // never mid-fill. One tick per row the page will instantiate.
      root._searchBuildStart(root.searchRowTotal(groups))
      root.applySearchGroups(groups, false)
      root.registerPinnedArtists()
      var any = root.searchRowTotal(groups);
      // A failed fetch is not an empty catalog:
      // while the group's honest words stand, the page never also says
      // "no results for X", which reads as a search that came back
      // empty.
      root.searchNoResultsFor = any === 0 && root.searchGroupError === "" ? root.lastSearchQuery : ""
    }
    // Assign a NEW object so the `var` property fires a change notification
    // (mutating + reassigning the same reference does not update bindings).
    function onAlbumTracksLoaded(id, tracks) {
      var c = Object.assign({}, root.trackCache)
      c[id] = tracks
      root.trackCache = c
    }
    function onPlaylistTracksLoaded(id, tracks) {
      var c = Object.assign({}, root.playlistTrackCache)
      c[id] = tracks
      root.playlistTrackCache = c
    }
    function onArtistMetaLoaded(id, pop) {
      // TIDAL enriches its search artists in the background; the row
      // lives on that provider's group.
      var list = root.searchGroupList()
      for (var i = 0; i < list.length; ++i)
        list[i].updateArtistPop(id, pop)
    }
    function onArtistLoadFailed(id) {
      // A Back-restore whose artist reload failed (offline, API error):
      // onArtistLoaded never fires, so clear the latch here or history
      // recording stays dead until the next successful navigation.
      if (root._navRestoring)
        root._navRestoring = false
      if (root._artistRestoreState && root._artistRestoreState.id === ("" + id)) {
        root._artistRestoreState = null
        artistView.pendingRestoreKey = ""
        artistView.pendingRestoreY = -1
      }
    }
    function onArtistLoaded(p) {
      // Background revalidation of a cached page: update in place only
      // if the user is still looking at this artist, never navigate. Never
      // let a full-page refresh overwrite a library-scoped view of the same
      // artist (scoped loads never emit refresh, so this only guards the
      // full page from clobbering a scoped one at the same id).
      if (p.refresh) {
        if (!root.artistOpen || !root.artistData || root.artistData.libraryScoped || ("" + root.artistData.id) !== ("" + p.id))
          return
        artistView.holdScroll()
        // in-place swap: keep the user's spot
        root.artistData = p
        root.fillMedia(artistAlbumsModel, p.albums)
        root.fillMedia(artistEpModel, p.eps)
        root.fillMedia(artistTracksModel, p.tracks)
        root.fillMedia(artistVideosModel, p.videos || [])
        return
      }
      if (root.videoNow)
        root.closeVideo()
      // artist link from the video player
      if (root._navRestoring)
        root._navRestoring = false
      else
        root.navPush()
      root.markNav("artist render")
      root.artistData = p
      // A Back into this artist re-applies the snapshot's expansion state
      // (armed in navBack); any other load starts the page collapsed.
      var pr = root._artistRestoreState
      root._artistRestoreState = null
      if (pr && pr.id === ("" + p.id)) {
        root.resetExpandedAlbums(pr.ex)
        root.bioExpanded = !!pr.bio
      } else {
        root.bioExpanded = false
        root.resetExpandedAlbums({})
      }
      root.artistOpen = true
      // target-first (see openLibrary): keep Search inactive mid-switch
      root.libraryOpen = false
      root.fillMedia(artistAlbumsModel, p.albums)
      root.fillMedia(artistEpModel, p.eps)
      root.fillMedia(artistTracksModel, p.tracks)
      root.fillMedia(artistVideosModel, p.videos || [])
    }
    // The whole queue (a full resync); updateQueueCounts, at the end of
    // the reconcile, rebuilds every mirror and count from it.
    function onQueueChanged(q) {
      root.reconcileQueue(q)
    }
    // The delta protocol: only the rows concerned cross, and only they
    // are touched here.
    function onQueueRowsAdded(rows) {
      for (var i = 0; i < rows.length; ++i)
        root.queueRowAdd(rows[i])
    }
    function onQueueRowsChanged(rows) {
      for (var i = 0; i < rows.length; ++i)
        root.queueRowPatch(rows[i])
    }
    function onQueueRowsRemoved(qids) {
      root.queueRowsDrop(qids)
    }
    function onQueueItemProgress(qid, pct) {
      var i = root.queueRowIndexOf(qid)
      if (i >= 0)
        queueModel.setProperty(i, "progress", pct)
    }
    // queue-row album expansion: per-track snapshot + live updates
    // These three land per track EVENT (state changes, and a pct batch
    // twice a second while an album downloads), so the map is updated in
    // place with an explicit change signal: cloning the whole map per
    // event (Object.assign) made every tick cost a copy of every finished
    // album's ledger too, growing for the life of the session. Bindings
    // depend on the change signal, not on object identity, so they
    // re-evaluate exactly as they did under the reassignment.
    function onQueueTracksLoaded(qid, tracks) {
      // A row that has left takes its track list with it (queueRowsDrop),
      // so a list that arrives after it went is dropped rather than
      // stored: nothing would ever show it, and nothing would free it.
      if (root.queueRowIndexOf(qid) < 0)
        return
      // Stored in place (one signal, no wholesale copy): this arrives on
      // every expansion and on live ticks, where copying the whole map
      // made each tick cost more than the one before it.
      root.queueTracks[qid] = tracks
      root.queueTracksChanged()
    }
    function onQueueTrackState(qid, row) {
      var arr = root.queueTracks[qid]
      if (!arr)
        return
      // Every row carrying this id, not the first: a playlist or mix can
      // list the same track twice, and the engine reports the track once
      // (its registry is keyed by id), so both rows follow the one event.
      // Stopping at the first hit left the second copy at QUEUED for
      // good while onQueueTrackPct below moved its percentage.
      var copy = arr.slice(), found = false
      for (var i = 0; i < copy.length; ++i) {
        if (copy[i].id === row.id) {
          copy[i] = Object.assign({}, copy[i], {
            status: row.status,
            pct: row.pct,
            fpct: row.fpct || 0
          })
          // A delivered quality only arrives with the state change,
          // so keep the one already on the row when the event has
          // none rather than blanking the track's tier.
          if (row.quality)
            copy[i].quality = row.quality
          if (row.expected && !copy[i].expected)
            copy[i].expected = row.expected
          if (row.owned)
            copy[i].owned = row.owned
          found = true
        }
      }
      if (!found)
        copy.push({
          id: row.id,
          num: copy.length + 1,
          title: row.title,
          duration: row.duration,
          status: row.status,
          pct: row.pct,
          fpct: row.fpct || 0,
          quality: row.quality,
          expected: row.expected || "",
          owned: row.owned || ""
        })
      root.queueTracks[qid] = copy
      root.queueTracksChanged()
    }
    function onQueueTrackPct(qid, ticks) {
      var arr = root.queueTracks[qid]
      if (!arr)
        return
      var copy = arr.slice(), hit = false
      for (var i = 0; i < copy.length; ++i) {
        var p = ticks[copy[i].id]
        if (p !== undefined) {
          copy[i] = Object.assign({}, copy[i], {
            pct: p
          })
          hit = true
        }
      }
      if (!hit)
        return
      root.queueTracks[qid] = copy
      root.queueTracksChanged()
    }
    function onDownloadProgress(id, pct) {
      var h = root.dlHolder(id)
      if (h)
        h.pct = pct
    }
    function onDownloadState(id, st) {
      var h = root.dlHolder(id)
      if (h)
        h.st = st
    }
    // Preview resolves are async; drop any that arrive after the user moved
    // on to a different preview (guard on the current kind+id).
    function onPreviewReady(kind, id, url) {
      if (kind !== root.previewKind || id !== root.previewId)
        return
      previewPlayer.source = url
      previewPlayer.play()
    }
    function onPreviewState(kind, id, st) {
      if (kind !== root.previewKind || id !== root.previewId)
        return
      if (st === "error") {
        // Flash the button red briefly, then fall back to idle.
        root.previewError = kind + ":" + id
        root.stopPreview()
        previewErrorTimer.restart()
      } else if (st === "") {
        root.stopPreview()
      } else if (st === "loading") {
        root.previewLoading = true
      }
    }
    function onPreviewMeta(kind, id, title, artist, art, artistId, albumId, trackId, artists) {
      if (kind !== root.previewKind || id !== root.previewId)
        // superseded
        return
      root.previewNowTitle = title
      root.previewNowArtist = artist
      root.previewNowArt = art
      root.previewNowArtistId = artistId
      root.previewNowAlbumId = albumId
      root.previewNowTrackId = trackId
      root.previewNowArtists = artists || []
    }
    function onLoginUrlReady(url) {
      // Only the inline steps are listening: a URL landing after CANCEL
      // must not open a browser or latch the paste field.
      if (root.setupMode !== "tidal")
        return
      Qt.openUrlExternally(url)
      root.setupUrlOpened = true
    }
    function onSignInRequested(providerId) {
      root.openProviderSignIn(providerId)
    }
    function onBackRequested() {
      root.navBack()
    }
    function onForwardRequested() {
      root.navForward()
    }
    function onAppUpdateChecked(available, current, latest, manual) {
      root.appUpdAvailable = available
      root.appUpdLatest = latest
      // Toast on detection; re-shows each launch until dismissed or
      // acted on (per version). The status-bar notice stays regardless.
      // Only for the automatic (opt-in) startup check: a manual check
      // means the user is already on the Settings updater card, so a
      // toast pointing them at the update would be noise.
      if (available && !manual)
        updateToast.offer(latest)
    }
    // Once the new build is staged the notice would be advertising a
    // version the user already has; the Settings card carries the
    // restart prompt from here.
    function onAppUpdateStateChanged(state, message) {
      if (state === "done")
        root.appUpdAvailable = false
    }
  }

  // ====================================================================
  ColumnLayout {
    id: mainColumn
    anchors.fill: parent
    spacing: 0
    // Hidden until the launch sequence hands over (see bootOverlay).
    // Invisible must also mean inert: opacity does not gate input, so
    // without the enabled gate every control is live under the launch
    // screen from the first frame.
    // 0.004 is invisible but rendered; see root.bootWarming for why the
    // page is painted before the reveal asks for it.
    // root.uiShown, not the raw dial: a pending terms gate holds the whole
    // interface at nothing, painted and inert, however far the launch
    // sequence has run.
    opacity: root.uiShown > 0 ? root.uiShown : (root.bootWarming ? 0.004 : 0)
    enabled: root.uiShown > 0

    // Header
    // The top bar and the search controls share one surface: the panel
    // grows downward to reveal the search tier when on a page that uses it,
    // rather than a separate strip butted against the bar. The hairline
    // always rides the panel's bottom edge as it expands / collapses.
    Rectangle {
      id: consoleHeader
      Layout.fillWidth: true
      implicitHeight: 56 + searchTier.height
      color: root.surface0
      Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: root.border1
      }
      RowLayout {
        id: headerRow
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 56
        anchors.leftMargin: 22
        anchors.rightMargin: 22
        spacing: 12
        WaveMark {
          id: headerMark
          host: root
        }
        // Wordmark sized to fill the logo box height (sublabel removed).
        Text {
          text: "WAVES"
          color: root.textHi
          font.bold: true
          font.letterSpacing: 2.6
          font.pixelSize: 40
          Layout.alignment: Qt.AlignVCenter
        }
        Item {
          Layout.fillWidth: true
        }
        // nav tabs, dim phosphor cells at rest; the active tab is a lit
        // cell (accent-container fill, accent label) that wipes in via the
        // CRT tube-collapse animation. Labels are sentence case by design
        // while other buttons stay UPPERCASE.
        NavTab {
          label: "Browse"
          // Lit by origin, not by view flags: drilling into an artist
          // or album keeps the tab you came from highlighted.
          active: root.navOrigin === "browse" && !root.settingsOpen
          // No configured provider fills Browse: the
          // destination is hidden rather than left permanently
          // empty. The bridge's capability answer is the rule.
          visible: root.browseAvailable
          onClicked: root.openBrowse()
        }
        NavTab {
          label: "Search"
          active: root.navOrigin === "search" && !root.settingsOpen
          // First press returns to Search exactly as it was left
          // (artist page, expanded album, scroll); a second press
          // while already there resets to a blank search page.
          onClicked: root.openSearch()
        }
        NavTab {
          label: "My Music"
          active: root.navOrigin === "library" && !root.settingsOpen
          onClicked: root.openLibrary()
        }
        NavTab {
          label: "Settings"
          active: root.settingsOpen
          onClicked: {
            root.navPush()
            root.markNav("settings")
            root.setupOpen = false
            settingsOpen = true
            root.artistOpen = false
            root.libraryOpen = false
          }
        }
        // "Finish setup": onboarding is answered but no provider can
        // download yet. The body re-opens the welcome page; the ✕
        // dismisses this chip permanently (Settings -> Providers ->
        // "Set up providers" remains the way back).
        Row {
          visible: root.downloadsNeedSetup && !root.setupOpen && !root.welcomeDue
          spacing: 6
          Layout.alignment: Qt.AlignVCenter
          Rectangle {
            objectName: "setupChip"
            implicitHeight: 26
            implicitWidth: finishTxt.implicitWidth + 20
            radius: 13
            color: "transparent"
            border.color: root.accentDim
            Text {
              id: finishTxt
              anchors.centerIn: parent
              text: "FINISH SETUP"
              color: root.accent
              font.pixelSize: 11
              font.family: root.uiFont
              font.bold: true
              font.letterSpacing: 1.0
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: root.openSetupPage()
            }
          }
          Rectangle {
            objectName: "setupChipDismiss"
            implicitHeight: 26
            implicitWidth: 26
            radius: 13
            color: "transparent"
            border.color: root.border1
            Text {
              anchors.centerIn: parent
              text: "✕"
              color: root.textDim
              font.pixelSize: 11
            }
            MouseArea {
              objectName: "setupChipDismissArea"
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: root.dismissSetupChip()
            }
          }
        }
        // queue (outlined) with count badge
        Rectangle {
          objectName: "queueBtn"
          implicitHeight: queueBtnRow.implicitHeight + root.btnPadV * 2
          implicitWidth: queueBtnRow.implicitWidth + root.btnPadH * 2
          radius: root.btnRad
          activeFocusOnTab: true
          Accessible.role: Accessible.Button
          Accessible.name: "Queue, " + root.activeQueueCount + (root.activeQueueCount === 1 ? " active item" : " active items")
          Accessible.onPressAction: queueDrawer.open()
          Keys.onReturnPressed: function (event) {
            if (!event.isAutoRepeat) {
              event.accepted = true
              queueDrawer.open()
            }
          }
          Keys.onEnterPressed: function (event) {
            if (!event.isAutoRepeat) {
              event.accepted = true
              queueDrawer.open()
            }
          }
          Keys.onSpacePressed: function (event) {
            if (!event.isAutoRepeat) {
              event.accepted = true
              queueDrawer.open()
            }
          }
          color: "transparent"
          border.color: root.border1
          RowLayout {
            id: queueBtnRow
            anchors.centerIn: parent
            spacing: 7
            Ico {
              name: "arrow-down"
              color: root.accent
              size: 15
              bold: 10
            }
            Text {
              text: "QUEUE"
              color: root.textLo
              font.pixelSize: 13
              font.family: root.uiFont
              font.bold: true
              font.letterSpacing: root.btnTrack
            }
            Rectangle {
              visible: root.activeQueueCount > 0
              radius: 9
              color: root.accent
              implicitWidth: Math.max(18, qc.implicitWidth + 10)
              implicitHeight: 18
              Text {
                id: qc
                textFormat: Text.PlainText
                anchors.centerIn: parent
                text: root.activeQueueCount
                color: root.accentText
                font.family: root.mono
                font.pixelSize: 11
                font.bold: true
              }
            }
          }
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: queueDrawer.open()
          }
          Rectangle {
            anchors.fill: parent
            radius: root.btnRad
            color: "transparent"
            border.width: 2
            border.color: root.accent
            visible: parent.activeFocus
          }
        }
        // Per-provider status lights: one compact dot
        // per provider the bridge reports. The account actions live
        // with the accounts: sign-out is on the TIDAL card in
        // Settings. The dot's colour states availability; the word
        // rides the accessible name and a hover label, so the
        // header stays compact and no global offline word exists
        // to contradict a usable provider.
        Row {
          id: providerLightsRow
          objectName: "providerLights"
          spacing: 10
          Repeater {
            model: root.providerLights
            delegate: Item {
              id: light
              required property var modelData
              objectName: "providerLight_" + modelData.id
              readonly property string providerId: String(modelData.id)
              readonly property string lightState: String(modelData.state)
              readonly property string statusName: String(modelData.name) + ": " + String(modelData.word)
              implicitWidth: 16
              implicitHeight: 26
              Accessible.role: Accessible.StaticText
              Accessible.name: light.statusName
              Rectangle {
                objectName: "providerLightDot_" + light.providerId
                anchors.centerIn: parent
                width: 7
                height: 7
                radius: 3.5
                // The shared status-light vocabulary
                // (StatusLight.js), the same one the Settings
                // status rows read.
                color: StatusLight.colorFor(root, light.lightState)
              }
              Text {
                visible: lightHover.containsMouse
                anchors.right: parent.left
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: light.statusName
                color: root.textLo
                font.pixelSize: 11
                font.family: root.uiFont
              }
              MouseArea {
                id: lightHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.ArrowCursor
              }
            }
          }
        }
      }

      // Search tier: shares the bar's surface and slides down out of
      // it on Search / artist pages; collapses up on Settings / My Music. ----
      Item {
        id: searchTier
        anchors.top: headerRow.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        clip: true
        // Drop out of the scene graph entirely once fully collapsed
        // (visible stays true through the height animation). clip alone
        // is not enough: the sort dropdown's caret is a QtQuick.Shapes
        // item, and Shapes can leak through an ancestor's clip/opacity.
        visible: height > 0
        readonly property bool shown: !root.settingsOpen && !root.libraryOpen && !root.browseOpen
        height: shown ? tierContent.implicitHeight : 0
        Behavior on height {
          NumberAnimation {
            duration: 220
            easing.type: Easing.OutCubic
          }
        }

        ColumnLayout {
          id: tierContent
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          spacing: 0
          opacity: searchTier.shown ? 1 : 0
          Behavior on opacity {
            NumberAnimation {
              duration: 160
              easing.type: Easing.OutQuad
            }
          }

          // Search + sort
          RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 22
            Layout.rightMargin: 22
            Layout.topMargin: 10
            spacing: 10
            enabled: root.searchAvailable
            opacity: root.searchAvailable ? 1 : 0.5
            Rectangle {
              id: searchBox
              Layout.fillWidth: true
              implicitHeight: 44
              radius: 8
              color: root.surface2
              border.color: (searchField.activeFocus || searchDecoder.decoding) ? root.accent : root.outline
              Behavior on border.color {
                ColorAnimation {
                  duration: 160
                  easing.type: Easing.OutQuad
                }
              }

              // A genuine TIDAL link auto-resolves once it has decoded in: host must
              // be tidal.com or any *.tidal.com subdomain (e.g. listen.tidal.com) AND
              // have a path. Lookalikes (eviltidal.com, tidal.com.evil.com) never fire.
              function isTidalUrl(s) {
                var u = ("" + s).trim().replace(/^https?:\/\//i, "")
                var slash = u.indexOf("/")
                if (slash < 1)
                  return false
                // need a host and a path
                var host = u.substring(0, slash).toLowerCase().replace(/^[^@]*@/, "").replace(/:\d+$/, "")
                var path = u.substring(slash + 1)
                if (!path.length)
                  return false
                // need something to resolve
                return host === "tidal.com" || /\.tidal\.com$/.test(host)
              }
              // Matrix-decrypt paste-in; a pasted TIDAL link auto-searches once
              // settled. A paste-glyph click arms the same auto-search for plain
              // text too: the button means "search this", while a
              // bare Ctrl+V still only fills the field so a term can be edited.
              DecodeController {
                id: searchDecoder
                field: searchField
                glyph: pasteGlyph
                // The decode runs ~0.6s, long enough to click an
                // artist name meanwhile: snapshot _navSeq at paste
                // time and let the link auto-open only if the user
                // has not navigated anywhere since (same rule as
                // onSearchResults, and same artistOpen allowance:
                // the search box is live on artist pages).
                property int seqAtPaste: -1
                // One-shot: set by the paste glyph's click, latched by the
                // decode that click's paste starts, cleared by any other
                // text change (see the field's onTextChanged) so a stale
                // arm never fires on a later unrelated paste.
                property bool submitPending: false
                property bool submitArmed: false
                onBegun: function (isRestart) {
                  seqAtPaste = root._navSeq
                  // A restart is a replaced decode, not the glyph's paste:
                  // the arm must not transfer to text the user overwrote
                  // mid-decode, or a fill-meant edit would search itself.
                  submitArmed = submitPending && !isRestart
                  submitPending = false
                }
                onDecoded: function (text) {
                  var armed = submitArmed
                  submitArmed = false
                  if (!searchBox.isTidalUrl(text) && !armed)
                    return
                  if (seqAtPaste !== root._navSeq || root.browseOpen || root.libraryOpen || root.settingsOpen)
                    return
                  root.submitSearch(root.searchQueryText(text))
                }
              }

              RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 6
                spacing: 10
                Ico {
                  name: "search"
                  color: root.accent
                  size: 18
                }
                TextField {
                  id: searchField
                  objectName: "searchField"
                  Layout.fillWidth: true
                  Accessible.name: "Search, or paste a TIDAL or Apple Music link"
                  // Escape empties the box first (the next Escape
                  // leaves it), so a keyboard user can reset the
                  // term without selecting it by hand.
                  Keys.onEscapePressed: function (event) {
                    if (searchField.text === "" && !searchDecoder.decoding)
                      return
                    // A decode in flight would rewrite the text on its
                    // next tick: cancel it and disarm the paste arm too,
                    // or the cleared term resurrects and still searches.
                    searchDecoder.cancel()
                    searchDecoder.submitArmed = false
                    searchDecoder.submitPending = false
                    searchField.text = ""
                    event.accepted = true
                  }
                  placeholderText: "Search, or paste a TIDAL or Apple Music link…"
                  color: searchDecoder.decoding ? root.accent : root.textHi
                  placeholderTextColor: root.textLo
                  font.pixelSize: 15
                  background: Rectangle {
                    color: "transparent"
                  }
                  onAccepted: {
                    var qt = root.searchQueryText(text)
                    if (qt !== text)
                      text = qt
                    // show what is searched
                    root.submitSearch(qt)
                  }
                  // A click or Tab into a box that already holds a term selects
                  // the whole term (deferred one tick past the click's own caret
                  // placement, which would otherwise clear it) so the next
                  // keystroke replaces it. Only fires on the focus transition, so
                  // clicking again to reposition the caret mid-edit is left alone.
                  onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function () {
                      searchField.selectAll()
                    })
                  // Returning to the app must re-arm that select-all. The
                  // backend filter swallows WindowActivate/Deactivate (the
                  // app-switch freeze fix), so the scene keeps its focus item
                  // across a switch and the click that brings Waves back never
                  // replays the transition above: the term would sit unselected
                  // until a click away and back. Ride the window's active flag (a
                  // QWindow signal the swallow does not touch) to fire the same
                  // deferred select-all a real focus transition produces.
                  readonly property bool appActive: root.active
                  onAppActiveChanged: if (appActive && activeFocus)
                    Qt.callLater(function () {
                      searchField.selectAll()
                    })
                  // A standard paste (a multi-char jump typing can't produce) is
                  // detected and animated in, without ever reading the clipboard.
                  onTextChanged: {
                    var wasDecoding = searchDecoder.decoding
                    searchDecoder.noteTextChanged()
                    // Any change that is not part of a decode (typing, a clear,
                    // a too-short paste) disarms a pending glyph auto-search.
                    if (!wasDecoding && !searchDecoder.decoding)
                      searchDecoder.submitPending = false
                  }
                }
                PasteGlyph {
                  id: pasteGlyph
                  Layout.alignment: Qt.AlignVCenter
                  // standard OS paste into the field; the field's onTextChanged
                  // animates it. The app itself never reads the clipboard.
                  // submitPending is set AFTER clear() (whose own text change
                  // would disarm it) so the pasted text auto-searches once the
                  // decode settles.
                  onClicked: {
                    searchField.forceActiveFocus()
                    searchField.clear()
                    searchDecoder.submitPending = true
                    searchField.paste()
                    // A paste of three characters or fewer is not a jump typing
                    // could not produce, so noteTextChanged starts no decode and
                    // the field's own disarm drops the arm. A glyph click is
                    // explicit intent, not a guess, so run the decode on
                    // whatever actually landed. Nothing landing means an empty
                    // clipboard, which must stay inert.
                    if (!searchDecoder.decoding && searchField.text.length > 0) {
                      searchDecoder.submitPending = true
                      searchDecoder.run(searchField.text)
                    }
                    // paste() inserts synchronously, so any decode this click
                    // could start has already begun and latched the arm. An arm
                    // still pending here had nothing to latch it (an empty
                    // clipboard pastes no text) and must not wait around: a
                    // LATER bare Ctrl+V starts its own decode, whose onBegun
                    // reads the flag before the field's disarm can run, and a
                    // paste the user meant to edit would search itself.
                    searchDecoder.submitPending = false
                  }
                }
              }
            }
            ComboBox {
              id: sortBox
              implicitHeight: 44
              implicitWidth: 156
              model: ["Relevance", "Release date", "Name", "Popularity"]
              currentIndex: Math.max(0, root.sortKeys.indexOf(waves.wavesPref("search_sort")))
              onActivated: {
                waves.setWavesPref("search_sort", root.sortKeys[currentIndex])
                root.applySort()
              }
              background: Rectangle {
                radius: 8
                color: root.surface2
                border.color: sortBox.popup.visible ? root.accent : root.outline
              }
              contentItem: Text {
                textFormat: Text.PlainText
                text: sortBox.displayText
                color: root.textHi
                font.pixelSize: 14
                leftPadding: 14
                rightPadding: 28
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
              }
              indicator: ExpandChevron {
                x: sortBox.width - 26
                y: (sortBox.height - 18) / 2
                tile: 18
                glyph: 13
                showTile: false
                closedAngle: -90
                openAngle: 0
                // Blank the stroke as soon as the tier starts collapsing (not when
                // it finishes hiding): the caret is a QtQuick.Shapes node, and a
                // hidden Shape can keep painting its last-synced stroke.
                stroke: searchTier.shown ? root.accent : "transparent"
                open: sortBox.popup.visible
              }
              delegate: ItemDelegate {
                width: sortBox.width
                contentItem: Text {
                  textFormat: Text.PlainText
                  text: modelData
                  color: root.textHi
                  font.pixelSize: 14
                  verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                  color: highlighted ? root.surface3 : root.surface2
                }
                highlighted: sortBox.highlightedIndex === index
              }
              popup: Popup {
                y: sortBox.height + 4
                width: sortBox.width
                padding: 4
                implicitHeight: contentItem.implicitHeight + 8
                background: Rectangle {
                  radius: 8
                  color: root.surface2
                  border.color: root.outline
                }
                contentItem: ListView {
                  clip: true
                  implicitHeight: contentHeight
                  model: sortBox.popup.visible ? sortBox.delegateModel : null
                  ScrollBar.vertical: ScrollBar {}
                }
              }
            }
            Rectangle {
              implicitHeight: 44
              implicitWidth: 44
              radius: 8
              color: root.surface2
              border.color: root.outline
              opacity: sortBox.currentIndex === 0 ? 0.55 : 1
              ToolTip.text: "Sort direction needs Date, Name or Popularity — Relevance has no direction"
              ToolTip.visible: sortHover.containsMouse && sortTap.enabled === false
              Text {
                textFormat: Text.PlainText
                anchors.centerIn: parent
                text: root.sortAsc ? "↑" : "↓"
                color: sortBox.currentIndex === 0 ? root.textDim : root.textHi
                font.family: root.mono
                font.pixelSize: 18
              }
              MouseArea {
                id: sortHover
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
              }
              TapAction {
                id: sortTap
                objectName: "sortDirectionButton"
                anchors.fill: parent
                focusRadius: 8
                enabled: sortBox.currentIndex !== 0
                accessibleLabel: root.sortAsc ? "Sort ascending" : "Sort descending"
                onTriggered: {
                  root.sortAsc = !root.sortAsc
                  waves.setWavesPref("search_sort_asc", root.sortAsc)
                  root.applySort()
                }
              }
            }
            // No audio-quality picker here: one would duplicate the Quality
            // setting in Settings, setting the same value but never filtering
            // results. Results are capped to the Settings quality, so a control
            // here has nothing left to say.
          }

          // Type chips
          // Hidden until a search returns results; the chips then cascade
          // in (staggered fade + downward settle) as the bar grows down.
          RowLayout {
            objectName: "searchTypeChips"
            Layout.fillWidth: true
            Layout.leftMargin: 22
            Layout.topMargin: 8
            spacing: 8
            visible: root.searchAvailable && root.hasResults && !root.artistOpen && !root.settingsOpen && !root.libraryOpen && !root.browseOpen
            Repeater {
              model: [["all", "All"], ["artists", "Artists"], ["albums", "Albums"], ["tracks", "Tracks"], ["videos", "Videos"], ["playlists", "Playlists"], ["mixes", "Mixes"]]
              delegate: Rectangle {
                id: tchip
                required property var modelData
                required property int index
                readonly property bool on: root.filterType === modelData[0]
                radius: 8
                implicitHeight: 30
                implicitWidth: fchipRow.implicitWidth + 26
                color: on ? root.accentCont : "transparent"
                border.color: on ? root.accentDim : root.border1
                opacity: 0
                transform: Translate {
                  id: chipTr
                  y: -7
                }
                Row {
                  id: fchipRow
                  anchors.centerIn: parent
                  spacing: 7
                  Rectangle {
                    width: 6
                    height: 6
                    radius: 3
                    anchors.verticalCenter: parent.verticalCenter
                    color: tchip.on ? root.accent : root.textDim
                  }
                  Text {
                    textFormat: Text.PlainText
                    anchors.verticalCenter: parent.verticalCenter
                    text: tchip.modelData[1]
                    color: tchip.on ? root.accent : root.textLo
                    font.pixelSize: 13
                  }
                }
                TapAction {
                  objectName: "searchTypeChip"
                  anchors.fill: parent
                  accessibleLabel: tchip.modelData[1]
                  role: Accessible.RadioButton
                  checkable: true
                  checked: tchip.on
                  focusRadius: 8
                  onTriggered: root.filterType = tchip.modelData[0]
                }
                // Cascade in left-to-right the moment results land, decoupled
                // from the card build veil (searchBuilding): gating the chips on
                // the veil made them arrive late on a cold first search and flicker
                // out then back in on every re-search. They now appear as soon as
                // results exist and stay put while the cards paint behind the veil.
                // Reset when cleared.
                states: State {
                  name: "in"
                  when: root.hasResults
                  PropertyChanges {
                    target: tchip
                    opacity: 1
                  }
                  PropertyChanges {
                    target: chipTr
                    y: 0
                  }
                }
                transitions: [
                  Transition {
                    to: "in"
                    SequentialAnimation {
                      PauseAnimation {
                        duration: tchip.index * 45
                      }
                      ParallelAnimation {
                        NumberAnimation {
                          target: tchip
                          property: "opacity"
                          to: 1
                          duration: 240
                          easing.type: Easing.OutCubic
                        }
                        NumberAnimation {
                          target: chipTr
                          property: "y"
                          to: 0
                          duration: 300
                          easing.type: Easing.OutCubic
                        }
                      }
                    }
                  },
                  Transition {
                    from: "in"
                    ParallelAnimation {
                      NumberAnimation {
                        target: tchip
                        property: "opacity"
                        to: 0
                        duration: 120
                      }
                      NumberAnimation {
                        target: chipTr
                        property: "y"
                        to: -7
                        duration: 120
                      }
                    }
                  }
                ]
              }
            }
          }
          // bottom padding so the controls don't kiss the panel hairline
          Item {
            Layout.fillWidth: true
            implicitHeight: 10
          }
        }                 // ColumnLayout tierContent
      }                     // Item searchTier
    }                         // Rectangle consoleHeader

    // Browse page (TIDAL editorial: new / top / genres / moods / decades)
    // Sub-page crumb trail, pinned above the scroll area so the way back
    // is always reachable without scrolling to the top (mirrors the
    // artist page): the whole navHistory as pills, current page lit.
    Item {
      Layout.fillWidth: true
      Layout.topMargin: 8
      visible: root.browseOpen && !root.artistOpen && !root.settingsOpen && !root.libraryOpen && root.browsePageKey !== ""
      implicitHeight: 30
      clip: true
      NavCrumbTrail {
        host: root
        x: 22
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, parent.width - 44)
      }
    }
    // Two always-alive panes on a flip stand: the landing on one, the
    // drilled page on the other, and navigation only ever changes which
    // is visible. Neither is torn down by leaving, so Back arrives
    // complete, already scrolled, with nothing to rebuild and nothing
    // to restore. Content is only rebuilt when the DATA changes (a
    // fresh landing payload, a different drilled page), never by
    // navigation itself.
    Item {
      Layout.fillWidth: true
      Layout.fillHeight: true
      visible: root.browseOpen && !root.artistOpen && !root.settingsOpen && !root.libraryOpen
      // Fetch on first reveal too (e.g. the user signed in while
      // already on the tab); idempotent thanks to the loading flags
      // here and the in-flight guard backend-side.
      onVisibleChanged: {
        if (visible && root.signedIn && root.browseSections.length === 0 && !root.browseLoading) {
          root.browseLoading = true
          root.browseError = false
          waves.loadBrowse()
        } else if (visible && root.signedIn) {
          waves.refreshBrowse()
          // silent, throttled; repaints only on change
        }
      }

      // While the landing loads or builds, the ambient wave video
      // behind this transparent pane stays in view on purpose: the
      // "Reading the wire…" hint sits on the living water and the
      // finished rows then fade in over it (browseReveal), instead of
      // a black floor snapping to rows.
      BrowseScroll {
        id: browseLanding
        host: root
        anchors.fill: parent
        visible: root.browsePageKey === ""
        col: browseLandingCol
        Column {
          id: browseLandingCol
          // The 8px breathing space lives INSIDE the scroll area
          // (y), not as an outer margin: an outer gap showed a
          // band of raw background with scrolled rows cut off
          // floating above it.
          x: 22
          y: 8
          width: browseLanding.width - 44
          spacing: 8

          // The shared loading hint (WireHint.qml owns the look).
          WireHint {
            id: browseLandingHint
            active: root.signedIn && (root.browseLoading || root.browseBuilding)
            width: parent.width
            tint: root.textLo
            onScreen: root.onScreen
          }

          // TIDAL signed out: the landing has nothing to show, so
          // the pane names the provider and offers the sign-in
          // click instead of staying blank. The
          // destination itself exists while a configured provider
          // declares Browse and its session is the
          // bridge's browse answer: the CTA follows that, never a
          // hardcoded TIDAL state.
          Item {
            objectName: "browseSignInCta"
            visible: root.browseAvailable && !root.browseSignedIn
            width: parent.width
            height: browseCtaCol.height
            Column {
              id: browseCtaCol
              anchors.horizontalCenter: parent.horizontalCenter
              width: Math.min(parent.width, 460)
              topPadding: 96
              spacing: 12
              Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                textFormat: Text.PlainText
                text: "Browse the TIDAL catalog"
                color: root.textHi
                font.pixelSize: 22
              }
              Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                text: "Sign in to explore playlists, genres, moods and new releases."
                color: root.textLo
                font.pixelSize: 13
              }
              GateAction {
                objectName: "browseSignInAction"
                width: parent.width
                label: "Sign in to TIDAL"
                onClicked: root.openSetupSignIn()
              }
            }
          }

          Column {
            visible: root.signedIn && root.browseError
            width: parent.width
            spacing: 12
            Text {
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              text: "Browse could not be loaded"
              color: root.textLo
              font.pixelSize: 18
              topPadding: 80
            }
            Rectangle {
              anchors.horizontalCenter: parent.horizontalCenter
              implicitWidth: bLandRetryTxt.implicitWidth + root.btnPadH * 2
              implicitHeight: bLandRetryTxt.implicitHeight + root.btnPadV * 2
              radius: root.btnRad
              color: "transparent"
              border.color: root.accentDim
              Text {
                id: bLandRetryTxt
                anchors.centerIn: parent
                text: "RETRY"
                color: root.accent
                font.family: root.uiFont
                font.pixelSize: 12
                font.bold: true
                font.letterSpacing: root.btnTrack
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                  root.browseLoading = true
                  root.browseError = false
                  waves.loadBrowse()
                }
              }
            }
          }

          // Landing, console style: the Genres / Moods / Decades
          // chip sets lead the page (the art-first layout renders
          // the same data as colour tiles BELOW the content
          // shelves instead). No page-key term: the landing pane
          // stays alive behind a drilled page, tearing the chips
          // down here is exactly the rebuild the two-pane design
          // exists to avoid.
          Repeater {
            model: root.browseStyle === "console" && !root.browseLoading && !root.browseError ? [["ALL PLAYLISTS", root.plChips(root.browseChips.moods)], ["GENRES", root.browseChips.genres], ["MOODS & ACTIVITIES", root.browseChips.moods], ["DECADES", root.browseChips.decades]] : []
            // Async for the same reason as the content shelves
            // below: ~60 chips are a real chunk of the
            // browse-render turn.
            delegate: Loader {
              id: chipGroupLd
              required property var modelData
              width: browseLandingCol.width
              asynchronous: root._browseAsyncBuild
              opacity: root.browseReveal
              onLoaded: root._browseBuildTick()
              sourceComponent: chipGroupComp
              Component {
                id: chipGroupComp
                Column {
                  id: chipGroup
                  readonly property var modelData: chipGroupLd.modelData
                  width: browseLandingCol.width
                  spacing: 8
                  visible: modelData[1].length > 0
                  // The headline opens the whole set, exactly as the
                  // art-style cloud headlines do. Without it the console
                  // style had no route to the playlists-only view at all:
                  // its chips reach the mood folders, but openPlaylistsRoot
                  // (and with it every genre and decade playlist folder)
                  // was unreachable in this style.
                  SectionHeader {
                    label: chipGroup.modelData[0]
                    count: chipGroup.modelData[1].length
                    openable: true
                    onOpened: chipGroup.modelData[0] === "ALL PLAYLISTS" ? root.openPlaylistsRoot() : root.openBrowseCloud(chipGroup.modelData[0], chipGroup.modelData[1])
                  }
                  Flow {
                    width: parent.width
                    spacing: 8
                    Repeater {
                      model: chipGroup.modelData[1]
                      delegate: Rectangle {
                        id: bchip
                        required property var modelData
                        radius: 8
                        implicitHeight: 30
                        implicitWidth: bcRow.implicitWidth + 26
                        color: "transparent"
                        border.color: root.border1
                        Row {
                          id: bcRow
                          anchors.centerIn: parent
                          spacing: 7
                          Rectangle {
                            width: 6
                            height: 6
                            radius: 3
                            anchors.verticalCenter: parent.verticalCenter
                            color: root.textDim
                          }
                          Text {
                            textFormat: Text.PlainText
                            anchors.verticalCenter: parent.verticalCenter
                            text: bchip.modelData.title
                            color: root.textLo
                            font.pixelSize: 13
                          }
                        }
                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: bchip.modelData.pl ? root.openPlaylistsFolder(bchip.modelData.path, bchip.modelData.title) : root.openBrowseLink(bchip.modelData.path, bchip.modelData.title)
                        }
                      }
                    }
                  }
                }
              }
            }
          }

          // Content shelves. Fresh landing shelves load through
          // asynchronous Loaders: the browseSections assignment
          // turn only creates n empty Loaders (a few ms), and
          // each shelf's delegate tree then incubates across
          // frames, so the nav-tab strike animation keeps its
          // frames instead of freezing for the ~250 ms a
          // synchronous build of every shelf would take.
          Repeater {
            model: root.browseSections
            delegate: Loader {
              id: bsecLd
              required property var modelData
              required property int index
              width: browseLandingCol.width
              asynchronous: root._browseAsyncBuild
              // Invisible while the veil is up, but still laid out.
              opacity: root.browseBuilding ? 0 : 1
              onLoaded: root._browseBuildTick()
              sourceComponent: BrowseSection {
                host: root
                sec: bsecLd.modelData
                secIndex: bsecLd.index
                landing: true
                pane: browseLanding
                col: browseLandingCol
              }
            }
          }

          // Landing, art-first: genre / mood / decade colour-tile
          // shelves close the page, content first, wayfinding
          // last, the way the streaming services arrange their
          // home pages.
          Repeater {
            model: root.browseStyle === "art" && !root.browseLoading && !root.browseError ? [["All Playlists", root.plChips(root.browseChips.moods)], ["Genres", root.browseChips.genres], ["Moods & Activities", root.browseChips.moods], ["Decades", root.browseChips.decades]] : []
            // Async for the same reason as the content shelves above.
            delegate: Loader {
              id: tileGroupLd
              required property var modelData
              width: browseLandingCol.width
              asynchronous: root._browseAsyncBuild
              opacity: root.browseReveal
              onLoaded: root._browseBuildTick()
              sourceComponent: tileGroupComp
              Component {
                id: tileGroupComp
                Column {
                  id: tileGroup
                  readonly property var modelData: tileGroupLd.modelData
                  width: browseLandingCol.width
                  spacing: 8
                  visible: modelData[1].length > 0
                  Text {
                    id: cloudTitle
                    textFormat: Text.PlainText
                    // "›" marks the headline as openable, click to see
                    // the whole cloud as a wrapping grid, like every
                    // other section headline.
                    text: tileGroup.modelData[0] + "  ›"
                    color: cloudTitleMa.containsMouse ? "#ffffff" : root.textHi
                    font.pixelSize: 17
                    font.bold: true
                    width: parent.width
                    elide: Text.ElideRight
                    topPadding: 6
                    MouseArea {
                      id: cloudTitleMa
                      anchors.left: parent.left
                      anchors.top: parent.top
                      anchors.bottom: parent.bottom
                      width: Math.min(parent.width, parent.implicitWidth)
                      hoverEnabled: true
                      cursorShape: Qt.PointingHandCursor
                      onClicked: tileGroup.modelData[0] === "All Playlists" ? root.openPlaylistsRoot() : root.openBrowseCloud(tileGroup.modelData[0], tileGroup.modelData[1])
                    }
                  }
                  ListView {
                    width: parent.width
                    height: 204
                    orientation: ListView.Horizontal
                    spacing: 14
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: tileGroup.modelData[1]
                    delegate: BrowseTile {
                      host: root
                      required property var modelData
                      required property int index
                      title: modelData.title
                      path: modelData.path
                      idx: index
                      plOnly: !!modelData.pl
                    }
                    ShelfWheelRedirect {
                      pane: browseLanding
                    }
                    ShelfEdgeFades {}
                  }
                }
              }
            }
          }
        }
      }

      // The drilled page (playlist / album / mix / genre / cloud).
      // Rebuilt only when the page DATA changes; hidden, alive and
      // still positioned while the user is elsewhere, so returning to
      // the same page (another tab and back) costs nothing.
      BrowseScroll {
        id: browseDrill
        host: root
        anchors.fill: parent
        visible: root.browsePageKey !== ""
        col: browseDrillCol
        restoreKey: root.browsePageKey
        grows: true
        Column {
          id: browseDrillCol
          x: 22
          y: 8
          width: browseDrill.width - 44
          spacing: 8
          // Hidden (but still laid out, so heights resolve) until
          // the highlighted-track scroll has been applied: opening
          // an album from a track then reveals it already on the
          // row, never mid-jump. Entering the state has no
          // transition, so the un-scrolled top never shows; the
          // reveal then FADES in so the album eases into place
          // already scrolled instead of dropping in blank. Only
          // the reveal direction is animated (the Transition's
          // `to: ""`); a Behavior can't do direction here without
          // racing the pending change.
          opacity: 1
          states: State {
            name: "positioning"
            when: root.browseHighlightPending
            PropertyChanges {
              target: browseDrillCol
              opacity: 0
            }
          }
          transitions: Transition {
            to: ""   // leaving "positioning" == the reveal
            NumberAnimation {
              property: "opacity"
              duration: 260
              easing.type: Easing.OutCubic
            }
          }

          // Item header (playlist / mix / album page): a
          // full-width hero, the artwork doubles as a dimmed
          // backdrop so the strip above the track list isn't
          // mostly empty panel.
          Rectangle {
            id: browseItemHeader
            readonly property var hd: root.browsePage && root.browsePage.header ? root.browsePage.header : null
            // The kind is in the key ("item:<kind>:<id>") before the
            // payload is, so the eyebrow can name the page at once.
            readonly property string keyKind: root.browsePageKey.indexOf("item:") === 0 ? root.browsePageKey.split(":")[1] : ""
            readonly property string kind: hd ? ("" + (hd.kind || "")) : keyKind
            // Skeleton: the page is keyed and the opener gave it a
            // name or a cover, the payload is still on the wire.
            // The header paints those at once (the clicked card's
            // own title and art) and the facts fill in when the
            // list lands, instead of the whole strip waiting on
            // the slowest page of a long playlist. Held back for
            // highlight opens: those hide the whole column until
            // the row has centred itself (browseHighlightPending),
            // and a header that shows, vanishes and returns blinks.
            readonly property bool skeleton: hd === null && keyKind !== "" && root.browseHighlightId === "" && (root.browseTitleHint !== "" || root.browseArtHint !== "")
            // Provider badge: the payload id when it
            // has landed, else the key the page was opened with,
            // so the skeleton names its provider from the first
            // frame instead of flashing TIDAL.
            readonly property string mediaId: {
              var id = hd ? ("" + (hd.id || "")) : ""
              if (id === "" && root.browsePageKey.indexOf("item:") === 0)
                id = root.browsePageKey.split(":").slice(2).join(":")
              return id
            }
            readonly property var provider: waves.providerDescriptor(mediaId)
            visible: hd !== null || skeleton
            width: parent.width
            height: visible ? 224 : 0
            radius: 14
            clip: true
            color: root.surface
            border.color: root.border1
            // Backdrop, two layers: the card's cover (stand-in) under
            // the page's own, which fades up once decoded. One Image
            // whose source flipped would blank while the new one
            // loads. Square decode on both: the warm pool keys on an
            // exact size, so a pre-warmed cover is a hit here too.
            Image {
              id: bihBgUnder
              anchors.fill: parent
              source: root.browseArtHint
              fillMode: Image.PreserveAspectCrop
              sourceSize.width: 480
              sourceSize.height: 480
              opacity: 0.30
              visible: bihBgMain.status !== Image.Ready
              asynchronous: true
              cache: true
            }
            Image {
              id: bihBgMain
              anchors.fill: parent
              source: browseItemHeader.hd ? (browseItemHeader.hd.art || "") : ""
              fillMode: Image.PreserveAspectCrop
              sourceSize.width: 480
              sourceSize.height: 480
              opacity: status === Image.Ready ? 0.30 : 0
              Behavior on opacity {
                NumberAnimation {
                  duration: 220
                  easing.type: Easing.OutQuad
                }
              }
              asynchronous: true
              cache: true
            }
            // Left-to-right scrim: keep the caption side
            // readable, let the backdrop breathe on the right.
            Rectangle {
              anchors.fill: parent
              gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop {
                  position: 0.0
                  color: "#e6101318"
                }
                GradientStop {
                  position: 0.55
                  color: "#a0101318"
                }
                GradientStop {
                  position: 1.0
                  color: "#30101318"
                }
              }
            }
            Row {
              anchors.fill: parent
              anchors.margins: 22
              spacing: 24
              Art {
                id: bihArt
                host: root
                width: 180
                height: 180
                radius: 12
                hoverFx: true
                fxKind: browseItemHeader.hd ? ("" + (browseItemHeader.hd.kind || "")) : ""
                fxId: browseItemHeader.hd ? ("" + (browseItemHeader.hd.id || "")) : ""
                anchors.verticalCenter: parent.verticalCenter
                url: browseItemHeader.hd ? (browseItemHeader.hd.art || "") : ""
                // The clicked card's cover, up from the first frame.
                underUrl: root.browseArtHint
                // Provider badge over the poster's top-right.
                ProviderBadge {
                  id: bihProviderBadge
                  anchors.right: parent.right
                  anchors.top: parent.top
                  anchors.rightMargin: 8
                  anchors.topMargin: 8
                  descriptor: browseItemHeader.provider
                }
              }
              Column {
                spacing: 7
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 180 - 24
                Text {
                  textFormat: Text.PlainText
                  text: browseItemHeader.kind === "playlist" ? "PLAYLIST" : browseItemHeader.kind === "mix" ? "MIX" : browseItemHeader.kind === "album" ? "ALBUM" : ""
                  color: root.textDim
                  font.pixelSize: 11
                  font.family: root.uiFont
                  font.bold: true
                  font.letterSpacing: 1.5
                }
                // Title + the presence pill right beside it.
                Row {
                  width: parent.width
                  spacing: 10
                  Text {
                    id: bihTitle
                    textFormat: Text.PlainText
                    text: browseItemHeader.hd ? (browseItemHeader.hd.title || "") : root.browseTitleHint
                    color: root.textHi
                    font.pixelSize: 26
                    font.bold: true
                    width: Math.min(implicitWidth, parent.width - (bihPill.visible ? bihPill.width + 10 : 0) - (bihNew.visible ? bihNew.width + 10 : 0))
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                  }
                  LibraryTag {
                    id: bihPill
                    host: root
                    anchors.verticalCenter: parent.verticalCenter
                    // One pill for every album page you open, so the
                    // page you open next must not read as news.
                    settleKey: browseItemHeader.hd ? ("" + (browseItemHeader.hd.id || "")) : ""
                    visible: !!(browseItemHeader.hd && browseItemHeader.hd.kind === "album" && root.libraryPresence && root.libraryPresence.present)
                    have: root.libraryPresence ? (root.libraryPresence.local_tracks || 0) : 0
                    total: browseItemHeader.hd ? (browseItemHeader.hd.num_tracks || 0) : 0
                    declared: root.libraryPresence ? (root.libraryPresence.local_declared || 0) : 0
                    albumId: root.libraryPresence ? (root.libraryPresence.local_album_id || "") : ""
                    qclass: root.libraryPresence ? (root.libraryPresence.local_class || "") : ""
                    // Same identity axis as the search-row pills: a proven
                    // match drops the "?" here too.
                    proven: !!(root.libraryPresence && root.libraryPresence.present && root.libraryPresence.sure === true)
                  }
                  // Capitals on the title's capitals: centred by
                  // box, the small mono word sat visibly high
                  // beside the 26px title.
                  FontMetrics {
                    id: bihTitleFm
                    font: bihTitle.font
                  }
                  NewTag {
                    id: bihNew
                    host: root
                    y: Math.round(bihTitle.y + bihTitle.baselineOffset - bihTitleFm.tightBoundingRect("H").height / 2 - capMiddle)
                    visible: !!(browseItemHeader.hd && browseItemHeader.hd.kind === "album" && root.isNewRelease(browseItemHeader.hd.date))
                    settled: bihDl.st === "done"
                  }
                }
                Text {
                  id: bihSubtitle
                  textFormat: Text.PlainText
                  text: browseItemHeader.hd ? (browseItemHeader.hd.subtitle || "") : ""
                  // Album subtitles carry the artist, make them read (and act) like a link.
                  readonly property bool linked: browseItemHeader.hd ? !!browseItemHeader.hd.artist_id : false
                  color: linked ? root.accentContTx : root.textLo
                  font.pixelSize: 14
                  width: parent.width
                  elide: Text.ElideRight
                  MouseArea {
                    anchors.fill: parent
                    enabled: bihSubtitle.linked
                    cursorShape: bihSubtitle.linked ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: waves.loadArtist(browseItemHeader.hd.artist_id)
                  }
                }
                Text {
                  textFormat: Text.PlainText
                  visible: text !== ""
                  text: browseItemHeader.hd ? (browseItemHeader.hd.desc || "") : ""
                  color: root.textLo
                  font.pixelSize: 12
                  width: parent.width
                  wrapMode: Text.WordWrap
                  maximumLineCount: 2
                  elide: Text.ElideRight
                }
                Text {
                  textFormat: Text.PlainText
                  visible: text !== ""
                  text: browseItemHeader.hd ? (browseItemHeader.hd.stats || "") : ""
                  color: root.textDim
                  font.pixelSize: 12
                  font.family: root.mono
                }
                Item {
                  width: 1
                  height: 3
                }
                Row {
                  spacing: 12
                  // Nothing to download until the payload says what.
                  visible: browseItemHeader.hd !== null
                  DownloadButton {
                    id: bihDl
                    host: root
                    mediaId: browseItemHeader.hd ? (browseItemHeader.hd.id || "") : ""
                    chooserKind: browseItemHeader.hd ? (browseItemHeader.hd.kind || "album") : "album"
                    label: browseItemHeader.hd ? (browseItemHeader.hd.kind === "playlist" ? "Download playlist" : browseItemHeader.hd.kind === "mix" ? "Download mix" : "Download album") : ""
                    collectionIds: root.collectionTrackIds(root.browsePage ? root.browsePage.sections : [])
                    // Album pages only (the header's artist/year facts are "" elsewhere,
                    // and a playlist must never wear an album's library state).
                    libAlbum: (browseItemHeader.hd && browseItemHeader.hd.kind === "album") ? ({
                        artist: browseItemHeader.hd.artist || "",
                        title: browseItemHeader.hd.title || "",
                        year: "" + (browseItemHeader.hd.year || ""),
                        tracks: browseItemHeader.hd.num_tracks || 0,
                        duration_sec: browseItemHeader.hd.duration_sec || 0
                      }) : null
                    onTap: function () {
                      if (browseItemHeader.hd)
                        root.browseCardDownload({
                          kind: browseItemHeader.hd.kind,
                          id: browseItemHeader.hd.id
                        })
                    }
                  }
                  StandalonePair {
                    visible: !!browseItemHeader.hd && browseItemHeader.hd.kind === "album"
                    mediaId: browseItemHeader.hd ? (browseItemHeader.hd.id || "") : ""
                    anchors.verticalCenter: parent.verticalCenter
                  }
                  // Playlists only: the full source album of every track.
                  // Its state lives under "albums:<id>", apart from the playlist button's.
                  DownloadButton {
                    host: root
                    visible: !!browseItemHeader.hd && browseItemHeader.hd.kind === "playlist"
                    mediaId: browseItemHeader.hd ? ("albums:" + (browseItemHeader.hd.id || "")) : ""
                    chooserKind: "playlistAlbums"
                    label: "Download full albums"
                    noun: "albums"
                    onTap: function () {
                      if (browseItemHeader.hd)
                        waves.downloadPlaylistAlbums(browseItemHeader.hd.id)
                    }
                  }
                }
              }
            }
          }

          // The shared loading hint (WireHint.qml owns the look).
          WireHint {
            id: browseDrillHint
            active: root.signedIn && root.browsePageLoading
            width: parent.width
            tint: root.textLo
            onScreen: root.onScreen
            // Under a skeleton header the hint belongs to the list
            // area just below it, not a screen's depth down.
            topPad: browseItemHeader.visible ? 40 : 96
          }

          Column {
            visible: root.signedIn && root.browsePageError
            width: parent.width
            spacing: 12
            Text {
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              text: "Browse could not be loaded"
              color: root.textLo
              font.pixelSize: 18
              topPadding: 80
            }
            Rectangle {
              anchors.horizontalCenter: parent.horizontalCenter
              implicitWidth: bDrillRetryTxt.implicitWidth + root.btnPadH * 2
              implicitHeight: bDrillRetryTxt.implicitHeight + root.btnPadV * 2
              radius: root.btnRad
              color: "transparent"
              border.color: root.accentDim
              Text {
                id: bDrillRetryTxt
                anchors.centerIn: parent
                text: "RETRY"
                color: root.accent
                font.family: root.uiFont
                font.pixelSize: 12
                font.bold: true
                font.letterSpacing: root.btnTrack
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.retryBrowsePage()
              }
            }
          }

          // Empty state: a drilled page that loaded fine but has
          // nothing Waves can render (e.g. an editorial article
          // page with no music). Better than a blank page below
          // the back bar.
          Text {
            visible: root.signedIn && root.browsePageKey !== "" && root.browsePage && !root.browsePageLoading && !root.browsePageError && ((root.browsePage.sections || []).length === 0)
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            textFormat: Text.PlainText
            text: "Nothing to show here"
            color: root.textLo
            font.pixelSize: 18
            topPadding: 96
          }

          // The drilled page's sections, synchronous: the
          // highlight machinery (browseHighlightPending + the
          // 120 ms centering timer) measures row positions right
          // after load and needs the full page laid out in one
          // turn. Long track lists are windowed inside
          // BrowseSection, so "the full page" is shells plus the
          // viewport, never five hundred built rows.
          Repeater {
            model: root.browsePage ? root.browsePage.sections : []
            delegate: BrowseSection {
              host: root
              required property var modelData
              required property int index
              width: browseDrillCol.width
              sec: modelData
              secIndex: index
              landing: false
              pane: browseDrill
              col: browseDrillCol
            }
          }
        }
      }
    }

    // Search results
    Flickable {
      id: results
      // Breathing space inside the scroll area (contentCol y), not as
      // an outer margin; see BrowseScroll.
      Layout.fillWidth: true
      Layout.fillHeight: true
      visible: !root.artistOpen && !root.settingsOpen && !root.libraryOpen && !root.browseOpen && !root.setupOpen
      clip: true
      contentWidth: width
      contentHeight: contentCol.height + 32
      ScrollBar.vertical: ScrollBar {}
      boundsBehavior: Flickable.StopAtBounds

      // Hold the scroll position steady across a window resize. The ARTISTS
      // row fills the width, so its cards (and the page height) grow and
      // shrink as the window is dragged; without this a shrink clamps
      // contentY to the new bottom and the page visibly jumps. Capture the
      // scroll ratio once at the start of a resize gesture and re-apply it on
      // every height change until the drag settles (140ms after the last
      // width change), so the view stays put. Scoped to an active resize, so
      // the build-in reveal of a fresh search (height grows with no width
      // change) is never touched.
      property real _resizeRatio: -1
      Timer {
        id: resizeSettle
        interval: 140
        onTriggered: results._resizeRatio = -1
      }
      onWidthChanged: {
        if (_resizeRatio < 0) {
          var span = contentHeight - height
          _resizeRatio = span > 0 ? contentY / span : 0
        }
        resizeSettle.restart()
      }
      onContentHeightChanged: {
        if (_resizeRatio < 0)
          return
        var maxY = Math.max(0, contentHeight - height)
        contentY = Math.min(_resizeRatio * maxY, maxY)
      }

      // While a search builds, the ambient wave video behind this
      // transparent pane stays in view on purpose: the "Reading the
      // wire…" hint sits on the living water and the finished result
      // cards then fade in over it (searchReveal), instead of a black
      // floor snapping to cards in one hard paint.
      Column {
        id: contentCol
        x: 22
        y: 8
        width: results.width - 44
        spacing: 8

        Text {
          id: emptyHint
          // The invitation is provider-agnostic: an Apple-only
          // signed-out search reaches it too. The
          // actions below carry whichever provider can fill it.
          visible: !root.hasResults
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          textFormat: Text.PlainText
          elide: Text.ElideMiddle
          // A search that found nothing says so; a search that
          // FAILED says that instead: the group's own message
          // carries the words, so the page
          // never invites a first search it already ran.
          text: root.searchNoResultsFor !== "" ? "No results for “" + root.searchNoResultsFor + "”" : (root.searchGroupError !== "" ? "Search failed" : "Search for an artist, album, or track to begin")
          color: root.textLo
          font.pixelSize: 22
          topPadding: 96
          // gentle breathing so the empty state feels alive
          SequentialAnimation on opacity {
            running: emptyHint.visible
            loops: Animation.Infinite
            NumberAnimation {
              from: 0.5
              to: 1.0
              duration: 1500
              easing.type: Easing.InOutSine
            }
            NumberAnimation {
              from: 1.0
              to: 0.5
              duration: 1500
              easing.type: Easing.InOutSine
            }
          }
        }

        // The empty state's one-click setup actions: instead of a
        // blank page, offer the click that would fill it. Apple search
        // needs no account; TIDAL needs a session. Each action retires
        // itself the moment its provider is set up.
        Item {
          objectName: "emptySetupCtas"
          visible: emptyHint.visible && (!root.appleEnabled || !root.signedIn)
          width: parent.width
          height: emptyCtaCol.height
          Column {
            id: emptyCtaCol
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width, 460)
            spacing: 10
            GateAction {
              objectName: "emptyAppleCta"
              width: parent.width
              visible: !root.appleEnabled
              label: "Enable Apple Music — search works without an account"
              // The bridge owns the rest of the enable flow
              // (search row, status light, the in-place wizard).
              onClicked: waves.applySettings({
                "apple_enabled": true
              })
            }
            GateAction {
              objectName: "emptyTidalCta"
              width: parent.width
              visible: !root.signedIn
              label: "Sign in to TIDAL"
              onClicked: root.openSetupSignIn()
            }
          }
        }

        // The shared loading hint (WireHint.qml owns the look).
        WireHint {
          id: searchBuildHint
          active: root.searchAvailable && root.searchBuilding
          width: parent.width
          tint: root.textLo
          onScreen: root.onScreen
        }

        // One group per provider that answered, in the payload's own
        // order (TIDAL, Apple, then any later provider): the shared
        // renderer reads each group's descriptor and rows, so a third
        // SEARCH provider lands here with no edit to this page.
        Repeater {
          id: searchGroupRep
          model: root.searchGroups.length
          delegate: SearchProviderGroup {
            host: root
            resultsPane: results
            groupData: root.searchGroups[index] || ({})
          }
        }
      }
    }

    // Artist page
    ColumnLayout {
      id: artistPane
      Layout.fillWidth: true
      Layout.fillHeight: true
      Layout.topMargin: 8
      visible: root.artistOpen && !root.settingsOpen && !root.libraryOpen
      // No gap between the back bar and the scroll area (rows would be
      // cut off floating over raw background); the 8px lives inside
      // artistView (artistCol y) instead.
      spacing: 0

      // Sticky crumb trail, stays put while the page scrolls: the whole
      // navHistory as pills, this artist as the last, lit one.
      Item {
        Layout.fillWidth: true
        Layout.leftMargin: 22
        implicitHeight: 26
        clip: true
        NavCrumbTrail {
          host: root
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          width: Math.min(implicitWidth, parent.width)
        }
      }

      Flickable {
        id: artistView
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        // Hold-in-place restore while a Back restore is armed, same
        // reasoning as BrowseScroll: the first frame lands on the saved
        // spot and content fills in around it, never a visible ratchet.
        readonly property real restorePad: pendingRestoreY >= 0 ? Math.max(0, pendingRestoreY + height - realContentH) : 0
        readonly property real realContentH: artistCol.height + 32
        contentWidth: width
        contentHeight: realContentH + restorePad
        ScrollBar.vertical: ScrollBar {}
        boundsBehavior: Flickable.StopAtBounds
        // A fresh artist page starts at the top; inheriting the previous
        // artist's scroll offset would open it part way down. A Back
        // that arms a restore lands on the saved spot instead. Same
        // pre-paint mechanism as
        // BrowseScroll: the restore is tagged with the artist id it
        // belongs to and applied on the id change and during layout
        // (onContentHeightChanged), before the frame paints, so Back
        // never visibly jumps. Explicit contentY writes (openSearch,
        // navBack same-artist) still win: they run after the id change.
        readonly property string _artistKey: root.artistData ? "" + (root.artistData.id || "") : ""
        property real pendingRestoreY: -1
        property string pendingRestoreKey: ""
        // mayDisarm: as on BrowseScroll, only a real layout pass may spend
        // the restore. On the id change contentHeight still belongs to
        // the outgoing page, so a tall one would disarm it before the
        // incoming artist has laid out.
        function applyRestore(mayDisarm) {
          if (pendingRestoreY < 0 || _artistKey !== pendingRestoreKey)
            return
          contentY = Math.min(pendingRestoreY, Math.max(0, contentHeight - height))
          // Real content only (pad excluded), as on BrowseScroll.
          if (mayDisarm && Math.max(0, realContentH - height) >= pendingRestoreY)
            pendingRestoreY = -1
          // reached the target
        }
        // Pin the spot across an in-place revalidate swap of the same
        // artist, exactly as BrowseScroll.holdScroll does.
        function holdScroll() {
          if (!visible || contentY <= 0 || moving)
            return
          pendingRestoreKey = _artistKey
          pendingRestoreY = contentY
        }
        on_ArtistKeyChanged: {
          if (pendingRestoreY >= 0 && _artistKey === pendingRestoreKey)
            applyRestore(false)
          else
            contentY = 0
        }
        onPendingRestoreYChanged: if (pendingRestoreY >= 0)
          artistRestoreGiveUp.restart()
        // Real height, not the padded contentHeight: see BrowseScroll.
        onRealContentHChanged: applyRestore(true)
        Timer {
          id: artistRestoreGiveUp
          interval: 800
          onTriggered: {
            artistView.pendingRestoreY = -1
            artistView.returnToBounds()
          }
        }

        Column {
          id: artistCol
          x: 22
          y: 8
          width: artistView.width - 44
          spacing: 12

          // Artist header, bio sits to the right of the photo, capped
          // to the photo height, with Read more for the rest.
          Row {
            width: parent.width
            spacing: 20
            Column {
              spacing: 10
              Art {
                id: artistArt
                host: root
                width: 150
                height: 150
                hoverFx: true
                fxKind: "artist"
                fxId: "" + (root.artistData.id || "")
                url: root.artistData.art || ""
                // Provider badge over the photo's top-right.
                // Hidden until the id is known, so a skeleton page
                // never flashes the wrong provider.
                ProviderBadge {
                  id: artistProviderBadge
                  anchors.right: parent.right
                  anchors.top: parent.top
                  anchors.rightMargin: 8
                  anchors.topMargin: 8
                  descriptor: waves.providerDescriptor(root.artistData.id || "")
                }
              }
              // No idle Preview button on the artist's own page, but if a
              // preview is already playing (e.g. started from a card), the
              // scrubber still surfaces here so it stays controllable.
              PreviewBar {
                host: root
                width: 150
                pid: root.artistData.id || ""
                visible: root.pvSt("artist", root.artistData.id || "") !== ""
              }
            }
            Column {
              width: parent.width - 170
              spacing: 8
              Text {
                text: "ARTIST"
                color: root.accent
                font.pixelSize: 12
                font.bold: true
                font.letterSpacing: 1.9
                topPadding: 8
              }
              Text {
                textFormat: Text.PlainText
                text: root.artistData.name || ""
                color: root.textHi
                font.pixelSize: 30
                font.bold: true
                width: parent.width
                elide: Text.ElideRight
              }
              // What you already hold by this artist, between the
              // name and the button that would add to it: the cards'
              // two voices standing on the page rather than on the
              // photograph.
              ArtistBadges {
                host: root
                artistName: root.artistData.name || ""
              }
              Row {
                spacing: 12
                DownloadButton {
                  host: root
                  objectName: "artistDownload"
                  mediaId: root.artistData.id || ""
                  chooserKind: "artist"
                  label: "Download discography"
                  // Only where the provider answers an artist
                  // sweep: Apple's catalog has no discography
                  // verb, and a live control that can only
                  // refuse is worse than none.
                  visible: waves.artistDownloadSupported(root.artistData.id || "")
                  // The badge directly above says what is held;
                  // this says what a click would add to.
                  libArtist: root.artistData.name || ""
                  onTap: function () {
                    waves.downloadArtist(root.artistData.id)
                  }
                }
                StandalonePair {
                  mediaId: root.artistData.id || ""
                  anchors.verticalCenter: parent.verticalCenter
                }
                // A library-scoped artist page (opened from My Music)
                // shows only owned releases; offer a jump to the artist's
                // full catalogue page. loadArtist() is the full path and
                // onArtistLoaded swaps the view (Back returns here).
                Text {
                  visible: !!root.artistData.libraryScoped
                  text: "View full artist page"
                  color: root.accent
                  font.pixelSize: 13
                  font.bold: true
                  anchors.verticalCenter: parent.verticalCenter
                  MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: waves.loadArtist(root.artistData.id || "")
                  }
                }
                Text {
                  text: "Copy link"
                  color: root.textLo
                  font.pixelSize: 13
                  anchors.verticalCenter: parent.verticalCenter
                  MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: waves.copyShareUrl("artist", root.artistData.id || "")
                  }
                }
              }
              // Collapsed bio preview (never taller than the photo)
              Text {
                visible: (root.artistData.bio || "") !== "" && !root.bioExpanded
                text: root.artistData.bio || ""
                textFormat: Text.PlainText  // never interpret remote bio as rich text (no auto <img> fetch)
                color: root.textLo
                font.pixelSize: 13
                width: parent.width
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
              }
              Text {
                textFormat: Text.PlainText
                visible: (root.artistData.bio || "") !== ""
                text: root.bioExpanded ? "SHOW LESS" : "READ MORE"
                color: root.accent
                font.pixelSize: 12
                font.letterSpacing: 0.8
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.bioExpanded = !root.bioExpanded
                }
              }
            }
          }
          // Full bio appears below the header only when expanded
          Text {
            visible: (root.artistData.bio || "") !== "" && root.bioExpanded
            text: root.artistData.bio || ""
            textFormat: Text.PlainText  // never interpret remote bio as rich text (no auto <img> fetch)
            color: root.textLo
            font.pixelSize: 13
            width: parent.width
            wrapMode: Text.WordWrap
            lineHeight: 1.3
          }

          // Top tracks: first 5 only, SHOW ALL reveals the rest. Both
          // the fold and the expansion persist across artists (prefs).
          SectionHeader {
            id: topTracksHead
            visible: artistTracksModel.count > 0
            label: "TOP TRACKS"
            count: artistTracksModel.count
            collapsible: true
            collapsed: root.artistTracksCollapsed
            onToggled: root.toggleArtistSection("tracks")
          }
          Repeater {
            // null model while collapsed: no delegates exist at all,
            // cheaper than count instances with visible: false.
            model: root.artistTracksCollapsed ? null : artistTracksModel
            delegate: TrackRow {
              host: root
              required property var model
              required property int index
              visible: index < 5 || root.topTracksExpanded
              width: artistCol.width
              tId: model.id
              title: model.title
              artistName: model.artist
              artistId: ""
              album: model.album
              art: model.art
              year: model.year
              date: model.date
              duration: model.duration
              durationSec: model.duration_sec || 0
              quality: model.quality
              popularity: model.popularity
              albumId: model.album_id || ""
            }
          }
          ShowAllLabel {
            host: root
            visible: !root.artistTracksCollapsed && artistTracksModel.count > 5
            sectionTop: topTracksHead
            expanded: root.topTracksExpanded
            count: artistTracksModel.count
            onToggled: root.toggleArtistExpand("tracks")
          }

          // Albums (expand inline): first 5, SHOW ALL for the rest, the
          // expansion remembered across artists like every section here.
          SectionHeader {
            id: artistAlbumsHead
            visible: artistAlbumsModel.count > 0
            label: "ALBUMS"
            count: artistAlbumsModel.count
            collapsible: true
            collapsed: root.artistAlbumsCollapsed
            onToggled: root.toggleArtistSection("albums")
          }
          Repeater {
            model: root.artistAlbumsCollapsed ? null : artistAlbumsModel
            delegate: AlbumBlock {
              host: root
              required property var model
              required property int index
              visible: index < 5 || root.artistAlbumsExpanded
              width: artistCol.width
              albumId: model.id
              title: model.title
              artistName: model.artist
              artistId: ""
              art: model.art
              year: model.year
              releaseDate: model.date
              listedDate: model.listed || ""
              trackCount: model.tracks
              durationSec: model.duration_sec || 0
              quality: model.quality
              popularity: model.popularity
            }
          }
          ShowAllLabel {
            host: root
            visible: !root.artistAlbumsCollapsed && artistAlbumsModel.count > 5
            sectionTop: artistAlbumsHead
            expanded: root.artistAlbumsExpanded
            count: artistAlbumsModel.count
            onToggled: root.toggleArtistExpand("albums")
          }

          // EPs & singles: same first-5 overview.
          SectionHeader {
            id: artistEpsHead
            visible: artistEpModel.count > 0
            label: "EPS & SINGLES"
            count: artistEpModel.count
            collapsible: true
            collapsed: root.artistEpsCollapsed
            onToggled: root.toggleArtistSection("eps")
          }
          Repeater {
            model: root.artistEpsCollapsed ? null : artistEpModel
            delegate: AlbumBlock {
              host: root
              required property var model
              required property int index
              visible: index < 5 || root.artistEpsExpanded
              width: artistCol.width
              albumId: model.id
              title: model.title
              artistName: model.artist
              artistId: ""
              art: model.art
              year: model.year
              releaseDate: model.date
              listedDate: model.listed || ""
              trackCount: model.tracks
              durationSec: model.duration_sec || 0
              quality: model.quality
              popularity: model.popularity
            }
          }
          ShowAllLabel {
            host: root
            visible: !root.artistEpsCollapsed && artistEpModel.count > 5
            sectionTop: artistEpsHead
            expanded: root.artistEpsExpanded
            count: artistEpModel.count
            onToggled: root.toggleArtistExpand("eps")
          }

          // Videos: the same art-first grid as the search results, at
          // the bottom of the page. The preview shows whole rows only
          // (at least 6: two rows of 3 at the usual width), because a
          // grid cut off at 5 leaves a hole where the sixth cell goes;
          // SHOW ALL reveals the rest, same as Top tracks, and the
          // collapse persists across artist pages.
          SectionHeader {
            id: artistVideosHead
            visible: artistVideosModel.count > 0
            label: "VIDEOS"
            count: artistVideosModel.count
            collapsible: true
            collapsed: root.artistVideosCollapsed
            onToggled: root.toggleArtistSection("videos")
            // Videos-only download-all:
            // deliberately independent of the "Music videos"
            // discography toggle, this button IS the explicit intent.
            // The "vids:" media id matches the backend's
            // _VIDEOS_GROUP_PREFIX group, so queued / running with
            // rollup % / done / failed all come from the shared
            // artist-group machinery.
            trailing: Component {
              DownloadButton {
                host: root
                mediaId: "vids:" + root.artistData.id
                chooserKind: "artistVideos"
                label: "All videos"
                onTap: function () {
                  waves.downloadArtistVideos(root.artistData.id)
                }
              }
            }
          }
          Flow {
            id: artistVideoGrid
            width: artistCol.width
            spacing: 18
            readonly property int cols: Math.max(2, Math.floor(width / 320))
            readonly property real cellW: (width - (cols - 1) * spacing) / cols
            readonly property int fillCount: Math.ceil(6 / cols) * cols
            Repeater {
              model: root.artistVideosCollapsed ? null : artistVideosModel
              delegate: VideoCell {
                host: root
                required property var model
                required property int index
                visible: index < artistVideoGrid.fillCount || root.artistVideosExpanded
                width: artistVideoGrid.cellW
                vid: model.id
                vcTitle: model.title
                vcArtist: model.artist
                artUrl: model.art
                artBigUrl: model.art_big || ""
                vcDuration: model.duration
                vcExplicit: model.explicit === true
                vcSpec: model.quality || ""
                vcDate: model.date
              }
            }
          }
          ShowAllLabel {
            host: root
            visible: !root.artistVideosCollapsed && artistVideosModel.count > artistVideoGrid.fillCount
            sectionTop: artistVideosHead
            expanded: root.artistVideosExpanded
            count: artistVideosModel.count
            onToggled: root.toggleArtistExpand("videos")
          }
        }
      }
    }

    // Provider welcome surface, re-opened as a page: no dim and no
    // click shield, so the nav stays usable and leaving is one click.
    Item {
      id: setupPane
      Layout.fillWidth: true
      Layout.fillHeight: true
      Layout.topMargin: 8
      visible: root.setupOpen
      WelcomePicker {
        host: root
        anchors.centerIn: parent
        onPicked: function (provider) {
          root.answerWelcome(provider)
        }
        onSkipped: root.answerWelcome("skip")
      }
    }

    // Settings page
    SettingsPage {
      id: settingsPage
      Layout.fillWidth: true
      Layout.fillHeight: true
      Layout.topMargin: 8
      visible: root.settingsOpen
      active: root.settingsOpen
      ff: appFfmpeg            // share the one app-wide FFmpeg manager
      onClosed: {
        root.settingsOpen = false
        setupOpen = false
      }
      // The Apple wizard's own skip: setup is deferred, not undone.
      // Apple stays enabled (search and previews keep working) and the
      // app lands on Search with the field focused, the same useful
      // landing a completed TIDAL sign-in gets.
      onAppleSetupSkipped: root.openSearch()
      onResetSettingsRequested: root.confirmSettingsReset = true
      onFactoryResetRequested: root.confirmFactoryReset = true
    }

    // Library page (My Music): the Library section first (ADR 0007 --
    // the files on disk, provider-independent), then one source group per
    // bridge source, each with its own category
    // strip and keep-alive panes, plus the one empty state while no
    // source can fill a shelf. The section list is bridge data, so a
    // second provider adds no QML here.
    ColumnLayout {
      id: libraryPane
      Layout.fillWidth: true
      Layout.fillHeight: true
      Layout.topMargin: 8
      visible: root.libraryOpen
      // No gap between the header row and the lists (see artistPane);
      // each list carries its own 8px inside the scroll area.
      spacing: 0

      LibLibrarySection {
        id: libSection
        host: root
        // The section shares the pane with the source groups. Its
        // share is bound, not fillHeight: QML's layout gives a
        // min/pref-hinting item the whole pane from its fill
        // siblings, and a bound share also keeps every section's
        // height stable while pages load into it.
        Layout.fillWidth: true
        Layout.fillHeight: false
        Layout.preferredHeight: Math.max(220, Math.round(libraryPane.height * 0.5))
        sectionData: root.myMusicLibrary
      }

      Item {
        id: libArea
        Layout.fillWidth: true
        Layout.fillHeight: true

        ColumnLayout {
          anchors.fill: parent
          spacing: 0
          Repeater {
            id: libSourceRep
            model: root.myMusicSources
            delegate: LibSourceGroup {
              host: root
              required property var modelData
              required property int index
              sourceData: modelData
              primary: index === 0
            }
          }
        }

        // No source can fill a shelf: one provider-named empty state
        // for the whole pane instead of a row of dead tabs. The words,
        // the provider and the action are the
        // bridge's answer, so a second provider names itself here with
        // no QML copy.
        Item {
          objectName: "libSignInCta"
          visible: root.myMusicSources.length === 0 && String(root.myMusicEmpty.message || "") !== ""
          anchors.fill: parent
          Column {
            id: libCtaCol
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width - 44, 460)
            topPadding: 96
            spacing: 12
            Text {
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              textFormat: Text.PlainText
              text: String(root.myMusicEmpty.message || "")
              color: root.textHi
              font.pixelSize: 22
            }
            Text {
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
              textFormat: Text.PlainText
              text: String(root.myMusicEmpty.detail || "")
              color: root.textLo
              font.pixelSize: 13
            }
            GateAction {
              objectName: "libSignInAction"
              width: parent.width
              label: String(root.myMusicEmpty.action_label || "")
              onClicked: root.runMyMusicEmptyAction()
            }
          }
        }

        // No placeholder for a signed-in category while it loads or
        // when it is empty. The pane is transparent, so the ambient
        // wave-loop background fills it on its own; a loading or
        // empty category simply shows the moving water, never a card
        // or glyph that flashes in for a beat and fades out. (The
        // waves are the brand presence here, so nothing else needs to
        // stand in.)
      }
    }

    // Status bar
    Rectangle {
      id: statusBar
      Layout.fillWidth: true
      implicitHeight: 28
      color: root.surface0
      Rectangle {
        anchors.top: parent.top
        width: parent.width
        height: 1
        color: root.border1
      }
      // Universal seek on the bottom playback line:
      // no expansion, so casual mouse travel can't trigger anything by
      // accident. The hit zone reaches 16px up from the edge so seeking
      // never means aiming at the window's resize-grab strip; an aim
      // tick + time flag ride the cursor and the single real seek fires
      // on release. Declared FIRST among the bar's children so the
      // status text and the mini player stack above it and keep their
      // clicks; presses land here only where nothing else claims them.
      Item {
        visible: root.previewKind !== "" && root.previewDuration > 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 16
        MouseArea {
          id: bottomSeekMa
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          preventStealing: true
          property bool scrubbing: false
          function frac(mx) {
            return width > 0 ? Math.max(0, Math.min(1, mx / width)) : 0
          }
          onPressed: function (m) {
            m.accepted = true
            scrubbing = true
            root.previewScrubbing = true
            root.scrubPreviewVisual(frac(m.x))
          }
          onPositionChanged: function (m) {
            if (scrubbing)
              root.scrubPreviewVisual(frac(m.x))
          }
          onReleased: function (m) {
            if (scrubbing) {
              scrubbing = false
              root.previewScrubbing = false
              root.seekPreview(frac(m.x))
            }
          }
          onCanceled: {
            scrubbing = false
            root.previewScrubbing = false
          }
        }
        // aim tick + time flag under the cursor
        Rectangle {
          visible: bottomSeekMa.containsMouse || bottomSeekMa.scrubbing
          x: bottomSeekMa.mouseX
          anchors.bottom: parent.bottom
          width: 1
          height: 10
          color: root.accentSoft
          opacity: 0.8
        }
        Rectangle {
          visible: bottomSeekMa.containsMouse || bottomSeekMa.scrubbing
          x: Math.max(4, Math.min(parent.width - width - 4, bottomSeekMa.mouseX - width / 2))
          anchors.bottom: parent.bottom
          anchors.bottomMargin: 16
          width: bottomSeekTxt.implicitWidth + 12
          height: 16
          radius: 4
          color: root.surfaceHi
          border.color: root.border1
          Text {
            id: bottomSeekTxt
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: root.fmtMs(bottomSeekMa.frac(bottomSeekMa.mouseX) * root.previewDuration)
            color: root.accentContTx
            font.family: root.mono
            font.pixelSize: 9
          }
        }
      }
      // Browse layout switch (art-first vs console), floating over the
      // pane's bottom-right corner so it costs the landing page no row.
      Rectangle {
        visible: root.signedIn && root.browseOpen && !root.artistOpen && !root.settingsOpen && !root.libraryOpen && root.browsePageKey === ""
        anchors.right: parent.right
        anchors.bottom: parent.top
        anchors.rightMargin: 22
        anchors.bottomMargin: 14
        radius: 14
        implicitHeight: 28
        implicitWidth: styleSeg.implicitWidth + 10
        color: "#e6101418"
        border.color: root.border1
        Row {
          id: styleSeg
          anchors.centerIn: parent
          spacing: 4
          Repeater {
            model: [["art", "ART"], ["console", "CONSOLE"]]
            delegate: Rectangle {
              id: schip
              required property var modelData
              readonly property bool on: root.browseStyle === modelData[0]
              radius: 10
              implicitHeight: 20
              implicitWidth: scText.implicitWidth + 16
              color: on ? root.accentCont : "transparent"
              Text {
                id: scText
                textFormat: Text.PlainText
                anchors.centerIn: parent
                text: schip.modelData[1]
                color: schip.on ? root.accent : (scMa.containsMouse ? root.textLo : root.textDim)
                font.pixelSize: 10
                font.family: root.uiFont
                font.bold: true
                font.letterSpacing: root.btnTrack
              }
              MouseArea {
                id: scMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setBrowseStyle(schip.modelData[0])
              }
            }
          }
        }
      }
      RowLayout {
        id: statusRow
        anchors.fill: parent
        anchors.leftMargin: 22
        anchors.rightMargin: 22
        spacing: 10
        // pulsing LED, bright when busy, dim otherwise
        Rectangle {
          width: 7
          height: 7
          radius: 3.5
          color: root.accent
          opacity: waves.busy ? 1 : 0.3
          SequentialAnimation on opacity {
            running: waves.busy
            loops: Animation.Infinite
            NumberAnimation {
              to: 0.35
              duration: 700
              easing.type: Easing.InOutSine
            }
            NumberAnimation {
              to: 1.0
              duration: 700
              easing.type: Easing.InOutSine
            }
          }
        }
        Text {
          id: statusText
          textFormat: Text.PlainText
          text: waves.status
          color: root.textLo
          font.family: root.mono
          font.pixelSize: 11
          // While the mini player is up, elide before its left edge so a
          // long status line never runs underneath the centered player.
          elide: Text.ElideRight
          Layout.maximumWidth: root.previewKind !== "" ? Math.max(60, nowPlaying.x - 51) : statusBar.width - 260
        }
        Item {
          Layout.fillWidth: true
        }
        // Logs console: realtime tail of the dev log for
        // debugging. Opens the drawer below; always on duty, update
        // notice or not.
        Text {
          id: logsBtn
          textFormat: Text.PlainText
          text: "LOGS"
          color: logsBtnMa.containsMouse ? root.textHi : root.textDim
          font.family: root.mono
          font.pixelSize: 11
          font.letterSpacing: 0.5
          Behavior on color {
            ColorAnimation {
              duration: 140
            }
          }
          MouseArea {
            id: logsBtnMa
            anchors.fill: parent
            anchors.margins: -4
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: logsDrawer.open()
          }
        }
        // Update notice: the right slot goes gold when a newer release is
        // waiting. Full line when the bar is idle; compacts to LED +
        // version while the mini player is up so the centre stays clear
        // (npInfo's budget subtracts this slot either way). Click opens
        // Settings, where the updater card carries the install button.
        RowLayout {
          id: statusUpdate
          visible: root.appUpdAvailable
          spacing: 7
          Rectangle {
            width: 7
            height: 7
            radius: 3.5
            color: root.gold
            SequentialAnimation on opacity {
              running: statusUpdate.visible
              loops: Animation.Infinite
              NumberAnimation {
                to: 0.35
                duration: 700
                easing.type: Easing.InOutSine
              }
              NumberAnimation {
                to: 1.0
                duration: 700
                easing.type: Easing.InOutSine
              }
            }
          }
          Text {
            textFormat: Text.PlainText
            text: root.previewKind !== "" ? "v" + root.appUpdLatest : "UPDATE · v" + root.appUpdLatest + " AVAILABLE"
            color: statusUpdMa.containsMouse ? root.goldContTx : root.gold
            font.family: root.mono
            font.pixelSize: 11
            font.letterSpacing: 0.5
            MouseArea {
              id: statusUpdMa
              anchors.fill: parent
              anchors.margins: -4
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              // Drop the user straight onto the Updates card
              // (already auto-expanded while an update waits);
              // callLater so the jump lands after the page's
              // onActiveChanged refresh has run.
              onClicked: {
                root.navPush()
                root.markNav("settings")
                root.setupOpen = false
                settingsOpen = true
                root.artistOpen = false
                root.libraryOpen = false
                Qt.callLater(function () {
                  settingsPage.jumpToCard("updates")
                })
              }
            }
          }
        }
        // Decorative, yield the right side to the now-playing bar when it
        // shows -- and to the update notice, which outranks a wordmark.
        RowLayout {
          id: statusMark
          visible: !root.appUpdAvailable
          spacing: 0
          opacity: root.previewKind !== "" ? 0 : 1
          Behavior on opacity {
            NumberAnimation {
              duration: 180
            }
          }
          // "checking" while the probe is out, "current" for a few
          // seconds after a check that found nothing. A check that
          // DOES find something needs no state here: appUpdAvailable
          // flips and the gold notice takes this slot instead.
          property string verState: ""
          Text {
            textFormat: Text.PlainText
            text: "TIDAL · WAVES CONSOLE · "
            color: root.textDim
            font.family: root.mono
            font.pixelSize: 11
            font.letterSpacing: 0.5
          }
          Text {
            id: verMark
            textFormat: Text.PlainText
            // Hover only brightens: swapping in a longer label would
            // shove the whole wordmark sideways under the cursor.
            // The transient check states are allowed to resize, they
            // follow a deliberate click.
            text: statusMark.verState === "checking" ? "CHECKING…" : statusMark.verState === "current" ? "UP TO DATE" : "v" + waves.appVersion
            color: statusMark.verState === "current" ? root.accent : verMa.containsMouse ? root.textLo : root.textDim
            font.family: root.mono
            font.pixelSize: 11
            font.letterSpacing: 0.5
            Behavior on color {
              ColorAnimation {
                duration: 140
              }
            }
            MouseArea {
              id: verMa
              anchors.fill: parent
              anchors.margins: -4
              hoverEnabled: true
              cursorShape: statusMark.verState === "checking" ? Qt.ArrowCursor : Qt.PointingHandCursor
              // The same check the Settings card runs. Not marked
              // manual: the user is nowhere near the updater, so a
              // found update should still raise its toast.
              onClicked: {
                if (statusMark.verState === "checking")
                  return
                statusMark.verState = "checking"
                waves.checkAppUpdate(false)
              }
            }
          }
          // A check that comes back empty says so, then goes quiet.
          Timer {
            id: verSettle
            interval: 3200
            onTriggered: statusMark.verState = ""
          }
          Connections {
            target: waves
            function onAppUpdateChecked(available, current, latest, manual) {
              if (statusMark.verState !== "checking")
                return
              statusMark.verState = available ? "" : "current"
              if (!available)
                verSettle.restart()
            }
          }
        }
      }
      // Now playing, persists across every view so playback can always be
      // paused/stopped, and clicking the title/artist jumps back to the
      // artist page (and expands the track's album). One shared player.
      // It docks to the bar's right corner whenever that corner is free
      // (the wordmark hides while playing) and slides to the centre only
      // when the update notice needs the corner, one animated move each
      // way so the controls never look like they are bouncing around.
      // Hovering anywhere on the bottom bar (not just the ✕) reveals the
      // mini player's "[stop]" label while something is playing.
      HoverHandler {
        id: npBarHover
      }
      Row {
        id: nowPlaying
        anchors.verticalCenter: parent.verticalCenter
        x: statusUpdate.visible ? (statusBar.width - width) / 2 : statusBar.width - width - 22
        Behavior on x {
          NumberAnimation {
            duration: 220
            easing.type: Easing.OutQuad
          }
        }
        spacing: 9
        visible: root.previewKind !== ""
        // Fixed box so swapping > / || / … never nudges the art + text. The
        // play caret is drawn larger so it stands at the pause bars' height.
        Item {
          anchors.verticalCenter: parent.verticalCenter
          // Always 20px. The transient "[buffering]" label paints
          // outside the box (leftward, over open bar space) so its
          // arrival and exit never resize the row: a resize moves the
          // right-docked row's x, and with the animated dock the whole
          // art + titles visibly slide when the stream becomes ready.
          width: 20
          height: 20
          Text {
            id: npGlyph
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: root.previewPlaying ? "||" : ">"
            color: root.accent
            font.family: root.mono
            font.bold: true
            font.pixelSize: root.previewPlaying ? 13 : 18
            // Steps aside for the buffering label, but only when
            // that label is actually showing: in a window too tight
            // for it the caret stays, so the box is never blank.
            opacity: (root.previewLoading && npBuffer.visible) ? 0 : 1
            Behavior on opacity {
              NumberAnimation {
                duration: 200
                easing.type: Easing.InOutSine
              }
            }
          }
          Text {
            id: npBuffer
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            textFormat: Text.PlainText
            text: "[buffering]"
            color: root.accent
            font.family: root.mono
            font.bold: true
            font.pixelSize: 10
            // It paints leftward, outside the box, into whatever bar
            // space is open between the status text and the row. That
            // space is not guaranteed: a narrow window with a long
            // title leaves less than the label needs, and the label
            // would print over the status text. Show it only when it
            // fits; the caret takes the box back when it does not.
            // Measured against the status text's REAL right edge (39
            // is where it starts: margin + busy dot + spacing) and not
            // against npInfo.leftGuard, which caps that width at a
            // fifth of the bar for its own budgeting.
            readonly property bool fits: (nowPlaying.x - 39 - statusText.width - 12) >= implicitWidth
            visible: root.previewLoading && fits
            property real breathe: 1
            opacity: breathe
            SequentialAnimation on breathe {
              // Gated on visible, not previewLoading alone: when
              // the label does not fit, animating the opacity of
              // a hidden item would still dirty the scene every
              // frame for the whole buffering period.
              running: npBuffer.visible
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
          MouseArea {
            anchors.fill: parent
            anchors.margins: -4
            cursorShape: Qt.PointingHandCursor
            onClicked: root.nowToggle()
          }
        }
        Art {
          host: root
          anchors.verticalCenter: parent.verticalCenter
          width: 18
          height: 18
          url: root.previewNowArt
        }
        Item {
          id: npInfo
          anchors.verticalCenter: parent.verticalCenter
          implicitWidth: npInfoRow.implicitWidth
          implicitHeight: npInfoRow.implicitHeight
          // Text budget. The bar is centered in the status Rectangle;
          // the right "console" caption is hidden while playing but the
          // update notice (statusUpdate) may hold that corner, so the
          // row is bounded by the wider of the two sides, then loses
          // the fixed controls (play +
          // art + stop + row gaps). Text shows in full when there's room
          // and elides only when the window is genuinely tight.
          // Cap the status text's claim at ~a fifth of the bar; it elides
          // to fit (see statusText), so a long status line no longer
          // floors the budget and crushes the artist for no reason.
          readonly property real leftGuard: 22 + 7 + 10 + Math.min(statusText.implicitWidth, statusBar.width * 0.22) + 24
          // The right slot is no longer guaranteed empty while playing:
          // the update notice stays up (compacted). Guard on whichever
          // side claims more so the centred row stays clear of both.
          readonly property real rightGuard: 22 + logsBtn.implicitWidth + 10 + (statusUpdate.visible ? statusUpdate.implicitWidth + 24 : 0)
          readonly property real fixedParts: 20 + 18 + stopMetrics.width + 27
          // Docked right (no update notice) the row spans from the
          // status text's guard to the bar's right margin; centred
          // (notice up) it is bounded symmetrically by the wider side.
          readonly property real budget: Math.max(120, statusUpdate.visible ? statusBar.width - 2 * Math.max(leftGuard, rightGuard) - fixedParts : statusBar.width - leftGuard - 22 - fixedParts)
          readonly property real sepW: npSep.implicitWidth + 12
          readonly property real avail: Math.max(60, budget - sepW)
          readonly property bool bothFit: (npTitle.implicitWidth + npArtist.implicitWidth) <= avail
          // When cramped, cap the artist to ~40% so the track title (the
          // thing you're more likely to want) keeps the larger share.
          readonly property real artistW: bothFit ? npArtist.implicitWidth : Math.min(npArtist.implicitWidth, avail * 0.42)
          readonly property real titleW: bothFit ? npTitle.implicitWidth : Math.max(48, avail - artistW)
          Row {
            id: npInfoRow
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            // Track name → its album page, track highlighted (fade).
            Text {
              id: npTitle
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.previewNowTitle
              color: npTitleMa.containsMouse && root.previewNowAlbumId !== "" ? "#ffffff" : root.textHi
              font.family: root.mono
              font.pixelSize: 11
              elide: Text.ElideRight
              width: Math.min(implicitWidth, npInfo.titleW)
              font.underline: npTitleMa.containsMouse && root.previewNowAlbumId !== ""
              MouseArea {
                id: npTitleMa
                anchors.fill: parent
                anchors.topMargin: -6
                anchors.bottomMargin: -6
                hoverEnabled: true
                cursorShape: root.previewNowAlbumId !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.nowOpenAlbum()
              }
            }
            Text {
              id: npSep
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: "·"
              color: root.textDim
              font.pixelSize: 11
            }
            // Artist credits, each collaborator its own clickable
            // name → that artist's page. Clipped (not per-name elided)
            // when the bar is tight; the whole line still shows in
            // full whenever there's room (see npInfo's budget).
            Item {
              id: npArtist
              anchors.verticalCenter: parent.verticalCenter
              readonly property var list: (root.previewNowArtists && root.previewNowArtists.length > 0) ? root.previewNowArtists : (root.previewNowArtist !== "" ? [
                  {
                    name: root.previewNowArtist,
                    id: root.previewNowArtistId
                  }
                ] : [])
              implicitWidth: npArtistsRow.implicitWidth
              implicitHeight: npArtistsRow.implicitHeight
              width: Math.min(implicitWidth, npInfo.artistW)
              clip: true
              Row {
                id: npArtistsRow
                anchors.verticalCenter: parent.verticalCenter
                Repeater {
                  model: npArtist.list
                  delegate: Row {
                    required property var modelData
                    required property int index
                    Text {
                      id: npArtName
                      readonly property bool linkable: !!modelData.id && modelData.id !== "" && !root.onArtistPage(modelData.id)
                      anchors.verticalCenter: parent.verticalCenter
                      textFormat: Text.PlainText
                      text: modelData.name
                      color: npArtMa.containsMouse && linkable ? "#ffffff" : root.accent
                      font.family: root.mono
                      font.pixelSize: 11
                      font.underline: npArtMa.containsMouse && linkable
                      MouseArea {
                        id: npArtMa
                        anchors.fill: parent
                        anchors.topMargin: -6
                        anchors.bottomMargin: -6
                        hoverEnabled: true
                        cursorShape: npArtName.linkable ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: if (npArtName.linkable)
                          waves.loadArtist(modelData.id)
                      }
                    }
                    Text {
                      visible: index < npArtist.list.length - 1
                      anchors.verticalCenter: parent.verticalCenter
                      textFormat: Text.PlainText
                      text: ", "
                      color: root.textDim
                      font.family: root.mono
                      font.pixelSize: 11
                    }
                  }
                }
              }
            }
          }
        }
        // Red at rest; reveals "[stop]" on hover. The box reserves the wider
        // "[stop]" width so the hover swap never reflows the now-playing text.
        Item {
          anchors.verticalCenter: parent.verticalCenter
          height: 20
          width: stopMetrics.width
          TextMetrics {
            id: stopMetrics
            font.family: root.mono
            font.pixelSize: 11
            font.bold: true
            text: "[stop]"
          }
          Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: (npBarHover.hovered || npStopMa.containsMouse) ? "[stop]" : "✕"
            color: root.red
            font.family: root.mono
            font.bold: true
            font.pixelSize: (npBarHover.hovered || npStopMa.containsMouse) ? 11 : 12
          }
          MouseArea {
            id: npStopMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.nowStop()
          }
        }
      }
      // Playback position line along the very bottom edge, 4px so the
      // seek target sits clear of the window's resize-grab edge, with a
      // phosphor spark breathing at the playhead on the shared LED clock.
      Rectangle {
        id: bottomSeekLine
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        height: 4
        color: root.accent
        visible: root.previewKind !== "" && root.previewDuration > 0
        width: parent.width * root.pvFrac(root.previewKind, root.previewId)
      }
      Rectangle {
        visible: bottomSeekLine.visible
        x: bottomSeekLine.width - width / 2
        anchors.bottom: parent.bottom
        width: 5
        height: 5
        radius: 1
        color: root.accentSoft
        opacity: 0.35 + 0.65 * root.ledPulse
      }
    }
  }

  // Clicking anywhere outside a focused text field releases its focus (caret
  // stops blinking, outline fades back), the way native fields behave. Covers
  // the search box and every settings path field alike. A PointHandler, and
  // specifically NOT the two obvious alternatives: a full-window MouseArea
  // would carry the default Arrow cursor and override every button's
  // pointing hand while the search field holds focus (which openSearch's
  // auto-focus makes permanent on that page), and a TapHandler SWALLOWS the
  // click, so navigating away from search would take one click to unfocus
  // and a second to actually land. A
  // PointHandler only observes: the same press both releases focus and
  // reaches the control under it, and no cursor is overridden.
  Item {
    id: focusDismissCatcher
    anchors.fill: parent
    z: 1000
    PointHandler {
      enabled: {
        var i = root.activeFocusItem
        return i !== null && (i instanceof TextInput || i instanceof TextEdit)
      }
      acceptedButtons: Qt.AllButtons
      onActiveChanged: {
        if (!active)
          return
        var t = root.activeFocusItem
        if (!t || !(t instanceof TextInput || t instanceof TextEdit))
          return
        // The search field's bounds are its whole styled box, so a click
        // on the box chrome (paste glyph and friends) keeps focus.
        var bounds = (t === searchField) ? searchBox : t
        var p = focusDismissCatcher.mapToItem(bounds, point.position.x, point.position.y)
        if (p.x < 0 || p.y < 0 || p.x > bounds.width || p.y > bounds.height)
          t.focus = false
      }
    }
  }

  // Sort the original full search data (not a lossy model copy) so every
  // field, including the full date, survives re-sorting. One control, every
  // provider group: each group re-orders its own albums, tracks and videos.
  // Artists, playlists and mixes carry no date to sort by and stay in the
  // API's relevance order.
  //
  // Relevance is the provider's own order, kept as it arrived. Reading it as
  // "popularity, most first" would bury exactly the result a specific
  // search is after: a single released this week has a popularity of 0
  // and sits under every older track that shares one word with the query,
  // while the provider ranks it first. Popularity is its own option.
  //
  // inPlace: a refresh swapping rows under a page the user is already
  // reading, where a clear+rebuild would freeze the window (see
  // reconcileById). Every other caller, the sort control included, is a
  // deliberate full rebuild of a small model.
  function applySort(inPlace) {
    var list = root.searchGroupList()
    for (var i = 0; i < list.length; ++i)
      list[i].applySort(inPlace === true)
  }
  // The order one group's raw rows land in, the sort control's rule in one
  // place (see applySort above).
  function searchOrdered(raw, hasPop) {
    var dir = root.sortAsc ? 1 : -1
    var arr = (raw || []).slice()
    if (sortBox.currentIndex === 1)
      arr.sort(function (a, b) {
        return dir * ((a.listed || a.date || a.year || "").localeCompare(b.listed || b.date || b.year || ""))
      })
    else if (sortBox.currentIndex === 2)
      arr.sort(function (a, b) {
        return dir * a.title.localeCompare(b.title)
      })
    else if (sortBox.currentIndex === 3 && hasPop)
      arr.sort(function (a, b) {
        return dir * ((a.popularity || 0) - (b.popularity || 0))
      })
    else if (root.sortAsc)
      arr.reverse()
    // Relevance (or no popularity data): the API's order, the arrow flips it
    return arr
  }

  // ====================================================================
  // Queue drawer
  // ====================================================================
  QueueDrawer {
    id: queueDrawer
    host: root
    queueModel: queueModel
  }

  // ====================================================================
  // Logs drawer
  // ====================================================================
  LogsDrawer {
    id: logsDrawer
    host: root
  }

  // ====================================================================
  // Scroll dressing
  // ====================================================================
  // One badge serves every page; it targets whichever scrollable is on
  // screen and stays hidden near the top of each.
  BackToTop {
    id: scrollDressing
    // Scroll dressing belongs to the interface, not to the launch screen:
    // it lives outside the main column, so without this it painted its
    // edge fades over the opening water at full strength (the landing is
    // scrollable from the first frame, so the bottom fade was always on).
    // uiShown, so a pending terms gate keeps it down too.
    opacity: root.uiShown
    flick: root.artistOpen ? artistView : root.libraryOpen ? root.libActiveView(root.libraryCategory) : root.browseOpen ? (root.browsePageKey === "" ? browseLanding : browseDrill) : root.settingsOpen ? null : root.setupOpen ? null : results
  }

  // First-run gate: the only place the welcome is not optional. Skip is
  // inside the card, so the surface can always be answered. Choosing TIDAL
  // does not answer it (answerWelcome leaves firstRunAnswered false), so
  // the gate stays up on the sign-in steps until they succeed or the user
  // cancels back to the cards.
  Rectangle {
    id: providerPicker
    anchors.fill: parent
    visible: root.welcomeDue
    // A fresh cold launch fades in with the rest of the interface.
    opacity: root.bootContentShown
    color: "#d606070e"
    MouseArea {
      anchors.fill: parent
    }
    WelcomePicker {
      host: root
      anchors.centerIn: parent
      onPicked: function (provider) {
        root.answerWelcome(provider)
      }
      onSkipped: root.answerWelcome("skip")
    }
  }

  // ====================================================================
  // FFmpeg setup gate, shown after sign-in. FFmpeg powers several core
  // features, so we nudge users toward the one-click managed install (the same
  // flow as Settings) while letting power-users map their own. It appears in
  // two cases:
  //   • first run, once, before the usage agreement (persisted via
  //     ffmpegSetupDone); and
  //   • a returning user whose FFmpeg has gone missing, re-prompted on launch
  //     so they're not silently left without it. "Later" snoozes that
  //     re-prompt for the session only (sessionSnoozed), so it's never naggy
  //     within a session but does check again next launch.
  // ====================================================================
  Settings {
    id: setupSettings
    category: "setup"
    property bool ffmpegSetupDone: false
    // "Don't show this again at launch": suppresses the ffmpeg-missing
    // re-prompt permanently for users who don't want FFmpeg at all.
    property bool ffmpegPromptDismissed: false
    // Update toast: the version the user last dismissed (✕) or acted on,
    // so that version stops toasting at launch; a NEWER release toasts.
    property string updateToastDismissed: ""
    // Update opt-in prompt (updateOptInGate): answered = either button was
    // pressed, the prompt never returns. A click-away answers nothing and
    // only counts a dismissal; after two of those it stops asking too.
    property bool updatePromptAnswered: false
    property int updatePromptDismissals: 0
    // True when this install went through the first-run terms gate, so
    // the opt-in prompt keeps its fresh-setup wording across launches.
    property bool updatePromptFresh: false
    // Exit warning (exitGate): "Don't warn me again" mutes the
    // downloads-still-running close prompt permanently.
    property bool exitWarnMuted: false
    // Onboarding: answered = the welcome surface was answered (a
    // provider card, a completed TIDAL sign-in, or Skip), so it never
    // returns automatically. Seeded once from the legacy provider-picker
    // bit by migrateOnboarding(); the setup popup below is the deliberate
    // way back.
    property bool firstRunAnswered: false
    // The "Finish setup" chip's ✕ is permanent; Settings -> Providers ->
    // "Set up providers" remains the way back.
    property bool setupChipDismissed: false
    // Legacy key, kept one release so the seed below can read
    // it. Nothing else may write it; delete with the next migration.
    property bool providerPickerDone: false
    // One-time seed: an answered picker means the user has seen the
    // first-run surface, and the old key is cleared so a later version
    // cannot resurrect the picker.
    function migrateOnboarding() {
      if (providerPickerDone && !firstRunAnswered)
        firstRunAnswered = true
      if (providerPickerDone)
        providerPickerDone = false
    }
  }
  FfmpegManager {
    id: appFfmpeg
    objectName: "appFfmpeg"
  }

  // Download-folder gate: no folder is set at all (fresh install). Blocks, the
  // download did not start; the CTA jumps straight to the Downloads setting.
  Rectangle {
    id: folderGate
    objectName: "folderGate"
    anchors.fill: parent
    visible: root.folderGateBlocking
    color: "#f406070e"
    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
    }   // eat clicks behind the card
    Rectangle {
      anchors.centerIn: parent
      width: 440
      implicitHeight: fgCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline
      ColumnLayout {
        id: fgCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          text: "Choose a download folder"
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          text: "Waves doesn't have a folder to save downloads to yet. Pick where your music should go, then start the download again."
        }
        GateAction {
          label: "Open download settings"
          onClicked: {
            root.folderGateBlocking = false
            root.openDownloadSetting()
          }
        }
        Text {
          Layout.alignment: Qt.AlignHCenter
          textFormat: Text.PlainText
          text: "Not now"
          color: root.textLo
          font.pixelSize: 13
          TapAction {
            objectName: "folderGateNotNow"
            anchors.fill: parent
            anchors.margins: -6
            accessibleLabel: "Not now"
            onTriggered: root.folderGateBlocking = false
          }
        }
      }
    }
  }

  // Download-folder nudge: still on the old "~/download" default. Blocking: the
  // download is held in the backend until the user decides. "Keep" continues it;
  // "Choose a new location" abandons it (they re-initiate after picking a folder),
  // so the download button never changes state until the decision is made.
  Rectangle {
    id: folderNudge
    objectName: "folderNudge"
    anchors.fill: parent
    visible: root.folderNudge
    color: "#cc06070e"
    MouseArea {
      anchors.fill: parent
      onClicked: {
        root.folderNudge = false
        waves.dismissDownloadFolderNudge()
      }
    }   // click-away cancels (no download)
    Rectangle {
      anchors.centerIn: parent
      width: 460
      implicitHeight: fnCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline
      MouseArea {
        anchors.fill: parent
      }   // a click on the card must not dismiss
      ColumnLayout {
        id: fnCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          wrapMode: Text.WordWrap
          text: "Would you like to update your download location?"
        }
        Text { // guard:deliberate-richtext download-nudge-body
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          textFormat: Text.StyledText
          linkColor: "#e6ebf0"
          // The path is a link: clicking it opens the OS file manager at that
          // folder (backend expands ~ and falls back to the nearest real dir).
          text: "Currently downloads are going to the default path <a href=\"reveal\"><tt>~/download</tt></a> the application shipped in v0.1.0, and that caused some issues with users being unable to locate their files, or not realizing they could update the default location for downloads.<br><br>Would you like to keep the current default, or choose a new location?"
          onLinkActivated: function (link) {
            waves.revealDownloadPath()
          }
        }
        RowLayout {
          Layout.fillWidth: true
          Layout.topMargin: 4
          spacing: 12
          GateAction {
            showArrow: false
            label: "Choose a new location"
            onClicked: {
              root.folderNudge = false
              waves.dismissDownloadFolderNudge()
              root.openDownloadSetting()
            }
          }
          GateAction {
            showArrow: false
            neutral: true
            label: "Keep the default location"
            onClicked: {
              root.folderNudge = false
              waves.keepDownloadFolder()
            }
          }
        }
      }
    }
  }

  // DOWNLOAD ALL on a Browse playlist category: state the size once,
  // confirm, with a persistent opt-out for heavy bulk users.
  Rectangle {
    id: catDlGate
    objectName: "catDlGate"
    anchors.fill: parent
    visible: root.catDlPrompt !== null
    color: "#cc06070e"
    MouseArea {
      anchors.fill: parent
      onClicked: root.catDlDismiss()
    }   // click-away cancels
    Rectangle {
      anchors.centerIn: parent
      width: 460
      implicitHeight: cdCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline
      MouseArea {
        anchors.fill: parent
      }   // a click on the card must not dismiss
      ColumnLayout {
        id: cdCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          wrapMode: Text.WordWrap
          text: root.catDlPrompt ? "Download " + root.catDlPrompt.count + (root.catDlPrompt.count === 1 ? " playlist?" : " playlists?") : ""
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          text: root.catDlPrompt ? "Everything in " + root.catDlPrompt.title + ", each playlist in its own folder. Progress shows in the queue." : ""
        }
        Row {
          spacing: 8
          Check {
            id: cdSkip
            objectName: "catDlSkipCheck"
            anchors.verticalCenter: parent.verticalCenter
            accessibleLabel: "Don't ask again"
            onToggled: checked = !checked
          }
          Text {
            textFormat: Text.PlainText
            anchors.verticalCenter: parent.verticalCenter
            text: "Don't ask again"
            color: root.textLo
            font.pixelSize: 13
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: cdSkip.checked = !cdSkip.checked
            }
          }
        }
        RowLayout {
          Layout.fillWidth: true
          Layout.topMargin: 4
          spacing: 12
          GateAction {
            showArrow: false
            label: "Download all"
            onClicked: {
              var p = root.catDlPrompt
              var mute = cdSkip.checked
              root.catDlDismiss()
              if (mute)
                waves.muteCategoryDlConfirm()
              if (p)
                waves.downloadPlaylistCategory(p.path)
            }
          }
          GateAction {
            showArrow: false
            neutral: true
            label: "Cancel"
            onClicked: root.catDlDismiss()
          }
        }
      }
    }
  }

  // Reset all settings to default (Advanced settings). Confirms before
  // anything happens; the reset keeps the account signed in and only puts
  // the settings-page values back to their factory defaults.
  Rectangle {
    id: settingsResetGate
    objectName: "settingsResetGate"
    anchors.fill: parent
    visible: root.confirmSettingsReset
    color: "#cc06070e"
    MouseArea {
      anchors.fill: parent
      onClicked: root.confirmSettingsReset = false
    }   // click-away cancels
    Rectangle {
      anchors.centerIn: parent
      width: 460
      implicitHeight: srCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline
      MouseArea {
        anchors.fill: parent
      }   // a click on the card must not dismiss
      ColumnLayout {
        id: srCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          wrapMode: Text.WordWrap
          text: "Reset all settings to default?"
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          text: "Every option in Settings goes back to its factory value, including your download folder and quality choices. You stay signed in, and your downloaded music is not touched."
        }
        RowLayout {
          Layout.fillWidth: true
          Layout.topMargin: 4
          spacing: 12
          GateAction {
            showArrow: false
            label: "Reset settings"
            onClicked: {
              root.confirmSettingsReset = false
              waves.resetSettingsDefaults()
              settingsPage.externalReset()
            }
          }
          GateAction {
            showArrow: false
            neutral: true
            label: "Cancel"
            onClicked: root.confirmSettingsReset = false
          }
        }
      }
    }
  }

  // Reset application (Advanced settings): the factory wipe. Confirms with
  // an explicit description of what is erased; on confirm the backend wipes
  // its saved state and the app closes so the next launch is a first run.
  Rectangle {
    id: factoryResetGate
    objectName: "factoryResetGate"
    anchors.fill: parent
    visible: root.confirmFactoryReset
    color: "#cc06070e"
    MouseArea {
      anchors.fill: parent
      onClicked: root.confirmFactoryReset = false
    }   // click-away cancels
    Rectangle {
      anchors.centerIn: parent
      width: 460
      implicitHeight: frCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline
      MouseArea {
        anchors.fill: parent
      }   // a click on the card must not dismiss
      ColumnLayout {
        id: frCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          wrapMode: Text.WordWrap
          text: "Reset Waves completely?"
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          text: "This signs you out and permanently erases everything Waves has saved on this computer: all settings, the record of which tracks you own, caches and logs. Your downloaded music files are not touched. Waves closes when it finishes, and the next launch starts like a brand-new install."
        }
        RowLayout {
          Layout.fillWidth: true
          Layout.topMargin: 4
          spacing: 12
          GateAction {
            showArrow: false
            danger: true
            label: "Erase everything and close"
            onClicked: {
              root.confirmFactoryReset = false
              waves.factoryReset()
              Qt.quit()
            }
          }
          GateAction {
            showArrow: false
            neutral: true
            label: "Cancel"
            onClicked: root.confirmFactoryReset = false
          }
        }
      }
    }
  }

  // Download folder set but unreachable (NAS asleep after lid close, drive
  // unplugged, stale mount). The download is held backend-side; "Try again"
  // re-runs it through the full gate (which also auto-heals a share that
  // remounted under a new /Volumes name).
  Rectangle {
    id: folderUnreachableGate
    objectName: "folderUnreachableGate"
    anchors.fill: parent
    visible: root.folderUnreachable
    color: "#cc06070e"
    MouseArea {
      anchors.fill: parent
      onClicked: {
        root.folderUnreachable = false
        waves.dismissDownloadFolderNudge()
      }
    }   // click-away cancels (no download)
    Rectangle {
      anchors.centerIn: parent
      width: 460
      implicitHeight: fuCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline
      MouseArea {
        anchors.fill: parent
      }   // a click on the card must not dismiss
      ColumnLayout {
        id: fuCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          wrapMode: Text.WordWrap
          text: "Download folder isn't reachable"
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WrapAnywhere
          color: root.textLo
          font.family: root.mono
          font.pixelSize: 12
          text: root.folderUnreachablePath
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          text: "The folder is set, but writing to it failed just now. If it lives on a network drive or NAS, it may have disconnected while the computer slept. Reconnect it, or choose a different folder. The download is held: Waves keeps checking and resumes on its own the moment the folder is back."
        }
        RowLayout {
          Layout.fillWidth: true
          Layout.topMargin: 4
          spacing: 12
          GateAction {
            showArrow: false
            label: "Try again"
            onClicked: {
              root.folderUnreachable = false
              waves.retryDownloadFolder()
            }
          }
          GateAction {
            showArrow: false
            neutral: true
            label: "Choose a new location"
            onClicked: {
              root.folderUnreachable = false
              waves.dismissDownloadFolderNudge()
              root.openDownloadSetting()
            }
          }
        }
      }
    }
  }

  Rectangle {
    id: ffmpegGate
    objectName: "ffmpegGate"
    anchors.fill: parent
    // First-run step (before terms) OR a returning user whose ffmpeg is now
    // missing (after terms, this session, not yet snoozed). The two branches
    // are mutually exclusive on termsCurrentAccepted (the same test the
    // terms gate shows on, version included), so this never stacks with
    // termsGate, a terms-revision re-prompt included.
    visible: root.signedIn && ((!setupSettings.ffmpegSetupDone && !root.termsCurrentAccepted) || (setupSettings.ffmpegSetupDone && root.termsCurrentAccepted && appFfmpeg.stateKey === "missing" && !ffmpegGate.sessionSnoozed && !setupSettings.ffmpegPromptDismissed))
    color: "#f406070e"
    // Eat every click; the only way past is the Continue / "later" choice.
    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
    }

    // Session-only snooze for the returning-user re-prompt: set by "later"
    // so the gate doesn't immediately re-show, but reset next launch.
    property bool sessionSnoozed: false

    // True once an install actually completes while this step is open, which
    // distinguishes "just installed" from "was already present" for the
    // title wording, without depending on FFmpeg-status load timing.
    property bool installedHere: false
    Connections {
      target: appFfmpeg
      function onLifeStateChanged() {
        if (appFfmpeg.lifeState === "done")
          ffmpegGate.installedHere = true
      }
    }

    Rectangle {
      anchors.centerIn: parent
      width: 460
      implicitHeight: ffCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline

      ColumnLayout {
        id: ffCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 13

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          text: appFfmpeg.ready ? (ffmpegGate.installedHere ? "Awesome, FFmpeg is installed!" : "Awesome, FFmpeg is already installed!") : "Set up FFmpeg"
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          text: appFfmpeg.stateKey === "managed" ? "Installed and managed by Waves. Video conversion, FLAC extraction, and downsampling are all available. You can manage or replace FFmpeg anytime in Settings." : appFfmpeg.stateKey === "path" ? "FFmpeg converts videos, extracts FLAC, and downsamples hi-res audio. Waves found a copy on your system and can use it as is." : "FFmpeg converts videos, extracts FLAC, and downsamples hi-res audio. Without it, those steps are skipped."
        }

        // Status readout: dot + FFMPEG + state, grouped on one line.
        RowLayout {
          Layout.fillWidth: true
          spacing: 8
          Rectangle {
            width: 7
            height: 7
            radius: 4
            Layout.alignment: Qt.AlignVCenter
            color: appFfmpeg.busy ? root.gold : appFfmpeg.stateKey === "managed" ? root.green : appFfmpeg.stateKey === "path" ? root.gold : root.red
          }
          Text {
            text: "FFMPEG"
            color: root.textHi
            font.pixelSize: 12
            font.bold: true
            font.letterSpacing: 1.4
          }
          Text {
            textFormat: Text.PlainText
            text: appFfmpeg.busy ? "INSTALLING" : appFfmpeg.stateKey === "managed" ? ("MANAGED" + (appFfmpeg.status.version ? " · " + appFfmpeg.status.version : "")) : appFfmpeg.stateKey === "path" ? ("SYSTEM" + (appFfmpeg.status.version ? " · " + appFfmpeg.status.version : "")) : "NOT INSTALLED"
            color: appFfmpeg.busy ? root.gold : appFfmpeg.stateKey === "managed" ? root.green : appFfmpeg.stateKey === "path" ? root.gold : root.textDim
            font.family: root.mono
            font.pixelSize: 10
            font.bold: true
            font.letterSpacing: 0.4
          }
          Item {
            Layout.fillWidth: true
          }
        }

        // Progress (while downloading/installing): the same LED
        // dot-matrix pill the Settings updater card uses.
        LedBar {
          visible: appFfmpeg.busy
          Layout.fillWidth: true
          radius: root.btnRad
          mono: root.mono
          pct: appFfmpeg.pct
          label: (appFfmpeg.message || "Working…") + " · " + Math.round(appFfmpeg.pct) + "%"
        }
        Text {
          textFormat: Text.PlainText
          visible: appFfmpeg.lifeState === "failed"
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          text: "Install failed: " + appFfmpeg.message
          color: root.red
          font.pixelSize: 12
        }

        // Missing: the choice is two tap cards, no separate confirm.
        GateCard {
          visible: appFfmpeg.stateKey === "missing" && !appFfmpeg.busy
          highlight: true
          title: "Install a managed copy"
          chip: "RECOMMENDED"
          desc: "Private to Waves, updated in one click from Settings."
          onClicked: appFfmpeg.install()
        }
        GateCard {
          objectName: "ffmpegGateLaterCard"
          visible: appFfmpeg.stateKey === "missing" && !appFfmpeg.busy
          title: "Set it up myself later"
          desc: "Point Waves at your own FFmpeg from Settings."
          onClicked: {
            setupSettings.ffmpegSetupDone = true
            ffmpegGate.sessionSnoozed = true
          }
        }
        Item {
          visible: appFfmpeg.stateKey === "missing" && !appFfmpeg.busy
          Layout.fillWidth: true
          implicitHeight: ffNoAskTxt.implicitHeight + 2
          Text {
            id: ffNoAskTxt
            anchors.centerIn: parent
            text: "I don't need FFmpeg. Stop showing this at launch."
            color: ffNoAskMa.containsMouse ? root.textHi : root.textLo
            font.pixelSize: 12
            font.underline: true
          }
          TapAction {
            id: ffNoAskMa
            objectName: "ffmpegGateNoAsk"
            anchors.fill: ffNoAskTxt
            accessibleLabel: "I don't need FFmpeg. Stop showing this at launch."
            onTriggered: {
              setupSettings.ffmpegPromptDismissed = true
              setupSettings.ffmpegSetupDone = true
              ffmpegGate.sessionSnoozed = true
            }
          }
        }

        // Detected on the system: keep it (continues) or switch to managed.
        GateCard {
          visible: appFfmpeg.stateKey === "path" && !appFfmpeg.busy
          highlight: true
          title: "Keep my system FFmpeg"
          chip: appFfmpeg.status.version ? "DETECTED · " + appFfmpeg.status.version : "DETECTED"
          desc: appFfmpeg.status.path ? "Use the copy already installed at " + appFfmpeg.status.path + "." : "Use the copy already installed on this system."
          onClicked: {
            setupSettings.ffmpegSetupDone = true
            ffmpegGate.sessionSnoozed = true
          }
        }
        GateCard {
          visible: appFfmpeg.stateKey === "path" && !appFfmpeg.busy
          title: "Switch to a managed copy"
          desc: "Private to Waves, one-click updates from Settings."
          onClicked: appFfmpeg.install()
        }

        // Cancel (while installing)
        GateAction {
          visible: appFfmpeg.busy
          label: "CANCEL"
          danger: true
          onClicked: appFfmpeg.cancel()
        }

        // Managed: continue past the gate.
        GateAction {
          visible: appFfmpeg.stateKey === "managed" && !appFfmpeg.busy
          label: "CONTINUE"
          onClicked: {
            setupSettings.ffmpegSetupDone = true
            ffmpegGate.sessionSnoozed = true
          }
        }

        // Source attribution, crediting the build maintainers.
        Text { // guard:deliberate-richtext ffmpeg-attribution
          visible: appFfmpeg.status.source ? true : false
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          textFormat: Text.StyledText
          linkColor: root.cyan
          color: root.textDim
          font.pixelSize: 11
          text: "Managed builds for " + (appFfmpeg.status.os || "") + "/" + (appFfmpeg.status.arch || "") + " come from <a href=\"" + (appFfmpeg.status.source_url || "") + "\">" + (appFfmpeg.status.source || "") + "</a>" + (appFfmpeg.status.source_license ? " · " + appFfmpeg.status.source_license : "") + ". Thank you to the maintainers. FFmpeg © the FFmpeg project (ffmpeg.org)."
          onLinkActivated: function (link) {
            Qt.openUrlExternally(link)
          }
        }
      }
    }
  }

  // Update toast: a newer Waves release was detected (launch check or a
  // manual one), and the WHOLE update flow runs inline here:
  //   offer      [gold dot] Waves vX is available     INSTALL   ✕
  //   installing [LedBar: download / verify / stage]  CANCEL
  //   ready      [green dot] vX installed             RESTART NOW   LATER
  //   failed     [red dot] Install failed: <reason>   RETRY   ✕
  // Shows on detection and again at every launch until the user dismisses
  // or acts on it (remembered per version); the gold status-bar notice
  // stays up regardless. Deliberately NO auto-hide: an update notice waits
  // until it is acted on in some way. The Settings updater card keeps its
  // own full controls; both listen to the same backend signals.
  Rectangle {
    id: updateToast
    objectName: "updateToast"
    // phase: "" (hidden) | "offer" | "installing" | "ready" | "failed"
    property string phase: ""
    // face: what the pill RENDERS. Tracks phase while shown but keeps the
    // last state during the fade-out, so dismissing never rebinds the
    // texts (RESTART NOW must not snap back to INSTALL mid-fade) and the
    // width never re-measures while collapsing.
    property string face: "offer"
    onPhaseChanged: if (phase !== "")
      face = phase
    property string version: ""
    property real pct: 0
    property string stage: ""
    property string error: ""
    // INSTALL works for a normal self-install AND for a package-manager
    // copy whose manager the app can run (brew upgrade). Only channels
    // without a runnable upgrade (Snap, Flatpak, an unknown sentinel)
    // fall back to VIEW (releases page). Snapshotted at offer time.
    property bool selfInstall: true
    function offer(v) {
      if (setupSettings.updateToastDismissed === v)
        return
      var st = waves.appUpdateStatus();
      // An update already staged and waiting for a restart outranks any
      // offer. install() deliberately refuses to stage a second one over
      // an armed helper (the two would race the same backup folder), so
      // it hands the STAGED result back whatever release it was asked
      // for: the toast offered the newer version, INSTALL reported that
      // newer version installed, and the restart landed the older one.
      // The staged version is what the next restart gives, so it is what
      // the pill goes on saying; the newer release is offered again by
      // the check that follows the restart.
      if (st && st.pending_restart === true)
        return
      selfInstall = st && (st.can_self_install === true || st.can_managed_install === true)
      version = v
      pct = 0
      phase = "offer"
    }
    // What a restart will actually land, whenever the app knows it: the
    // toast's own idea of the version is what it was asked to offer, and
    // an install that took over a staged swap never went near that release.
    function landedVersion() {
      var st = waves.appUpdateStatus();
      // The staged version comes straight off the release tag, which in
      // this project is spelled "v0.1.26", while everything the label
      // puts a "v" in front of has been through update_available()'s
      // strip. Unstripped it renders "Waves vv0.1.26 installed", on the
      // ordinary install too: every successful Windows install arms a
      // pending restart, so this is the usual path, not the rare one.
      var staged = st ? ("" + (st.pending_version || "")).replace(/^[vV]/, "") : ""
      return staged !== "" ? staged : version
    }
    function dismiss() {   // remembered for this version
      setupSettings.updateToastDismissed = version
      phase = ""
    }

    // Real updater lifecycle. Progress/stage bind only while this toast
    // drives the install; "done" flips any visible toast to the restart
    // prompt (even one still on "offer" while Settings ran the install).
    Connections {
      target: waves
      function onAppUpdateProgress(p) {
        if (updateToast.phase === "installing")
          updateToast.pct = p
      }
      // Staged in an earlier session and re-armed at this launch: show
      // the restart pill outright. Not an offer, so the per-version
      // dismissal does not apply, it is already downloaded and verified.
      function onAppUpdatePending(v) {
        updateToast.version = v
        updateToast.pct = 100
        updateToast.selfInstall = true
        updateToast.phase = "ready"
      }
      function onAppUpdateStateChanged(state, message) {
        if (updateToast.phase === "")
          return
        if (state === "downloading") {
          if (updateToast.phase === "installing")
            updateToast.stage = message
        } else if (state === "done") {
          updateToast.pct = 100
          updateToast.phase = "ready"
        } else if (state === "failed" && updateToast.phase === "installing") {
          updateToast.error = message
          updateToast.phase = "failed"
        } else if (state === "cancelled" && updateToast.phase === "installing") {
          updateToast.pct = 0
          updateToast.phase = "offer"
        }
      }
    }

    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 46
    // The pill widens while the LED bar is up, then narrows again.
    width: face === "installing" ? Math.min(560, parent.width - 40) : Math.min(utRow.implicitWidth + 28, parent.width - 40)
    Behavior on width {
      enabled: updateToast.phase !== ""
      NumberAnimation {
        duration: 200
        easing.type: Easing.OutCubic
      }
    }
    height: 40
    radius: 10
    color: root.surface2
    border.color: root.outline
    border.width: 1
    opacity: phase !== "" ? 1 : 0
    visible: opacity > 0
    Behavior on opacity {
      NumberAnimation {
        duration: 260
        easing.type: Easing.OutCubic
      }
    }
    // gentle settle down and away as it fades
    transform: Translate {
      y: updateToast.phase !== "" ? 0 : 10
      Behavior on y {
        NumberAnimation {
          duration: 260
          easing.type: Easing.OutCubic
        }
      }
    }

    RowLayout {
      id: utRow
      anchors.fill: parent
      anchors.leftMargin: 14
      anchors.rightMargin: 14
      spacing: 12

      // status dot (offer: gold / ready: green / failed: red)
      Rectangle {
        visible: updateToast.face !== "installing"
        width: 7
        height: 7
        radius: 4
        Layout.alignment: Qt.AlignVCenter
        color: updateToast.face === "ready" ? root.green : updateToast.face === "failed" ? root.red : root.gold
      }

      // main line (offer / ready / failed)
      Text {
        visible: updateToast.face !== "installing"
        Layout.alignment: Qt.AlignBaseline
        textFormat: Text.PlainText
        text: updateToast.face === "ready" ? "Waves v" + updateToast.landedVersion() + " installed" : updateToast.face === "failed" ? "Install failed: " + updateToast.error : "Waves v" + updateToast.version + " is available"
        color: updateToast.face === "failed" ? root.red : root.textHi
        font.pixelSize: 12
        elide: Text.ElideRight
        Layout.maximumWidth: root.width - 300
      }

      // the LED pill while installing (same bar as the Settings card)
      LedBar {
        visible: updateToast.face === "installing"
        Layout.fillWidth: true
        Layout.preferredHeight: 22
        Layout.alignment: Qt.AlignVCenter
        radius: 8
        mono: root.mono
        pct: updateToast.pct
        label: updateToast.stage + " · " + Math.round(updateToast.pct) + "%"
      }

      // primary action per phase: green. On hover the label runs a
      // console "decode": every glyph scrambles, then characters lock
      // in left to right while the tail keeps churning, with a bright
      // flash that fades as the word resolves. Deliberate, not a bug.
      // CANCEL (installing) stays plain grey: no glitch on it.
      Text {
        id: utAct
        Layout.alignment: Qt.AlignBaseline
        textFormat: Text.PlainText
        readonly property string realLabel: updateToast.face === "offer" ? (updateToast.selfInstall ? "INSTALL" : "VIEW") : updateToast.face === "installing" ? "CANCEL" : updateToast.face === "ready" ? "RESTART NOW" : "RETRY"
        property string scr: ""
        text: scr !== "" ? scr : realLabel
        color: updateToast.face === "installing" ? root.textDim : utGlitch.running ? Qt.lighter(root.green, 1.0 + 0.45 * (1 - utAct._gt / utGlitch.ticks)) : root.green
        font.family: root.mono
        font.pixelSize: 10
        font.bold: true
        font.letterSpacing: 0.8
        property int _gt: 0
        readonly property string _glyphs: "ABCDEF0123456789/:#@$%&*+=<>"
        Timer {
          id: utGlitch
          interval: 30
          repeat: true
          readonly property int ticks: 12
          onTriggered: {
            utAct._gt++
            if (utAct._gt > ticks) {
              utGlitch.stop()
              utAct.scr = ""
              return
            }
            // characters resolve left to right; the unresolved
            // tail keeps scrambling every tick
            var locked = Math.floor(utAct.realLabel.length * utAct._gt / ticks)
            var out = ""
            for (var i = 0; i < utAct.realLabel.length; i++)
              out += (i < locked || utAct.realLabel.charAt(i) === " ") ? utAct.realLabel.charAt(i) : utAct._glyphs.charAt(Math.floor(Math.random() * utAct._glyphs.length))
            utAct.scr = out
          }
        }
        TapAction {
          id: utGo
          objectName: "updateToastPrimary"
          anchors.fill: parent
          anchors.margins: -8
          // The spoken name follows the face's own word, so a reader hears
          // INSTALL / VIEW / CANCEL / RESTART NOW / RETRY as drawn.
          accessibleLabel: utAct.realLabel
          onEntered: if (updateToast.phase !== "installing") {
            utAct._gt = 0
            utGlitch.restart()
          }
          onTriggered: {
            if ((updateToast.phase === "offer" || updateToast.phase === "failed") && !updateToast.selfInstall) {
              // Package-manager-owned install: hand off to the
              // releases page, never write over the managed copy.
              waves.openReleasesPage()
              updateToast.dismiss()
            } else if (updateToast.phase === "offer" || updateToast.phase === "failed") {
              // acted on: stop re-showing at launch
              setupSettings.updateToastDismissed = updateToast.version
              updateToast.pct = 0
              updateToast.error = ""
              updateToast.stage = "Downloading update…"
              updateToast.phase = "installing"
              waves.installAppUpdate()
            } else if (updateToast.phase === "installing") {
              waves.cancelAppUpdate()
              // backend answers with state "cancelled"
            } else {
              waves.restartForUpdate()
            }
          }
        }
      }

      // secondary: ✕ (offer/failed) or LATER (ready); nothing mid-install
      Text {
        visible: updateToast.face !== "installing"
        Layout.leftMargin: 2
        Layout.alignment: Qt.AlignBaseline
        textFormat: Text.PlainText
        text: updateToast.face === "ready" ? "LATER" : "✕"
        color: utX.containsMouse ? root.textHi : root.textDim
        font.family: updateToast.face === "ready" ? root.mono : root.uiFont
        font.pixelSize: updateToast.face === "ready" ? 10 : 11
        font.bold: updateToast.face === "ready"
        font.letterSpacing: updateToast.face === "ready" ? 0.8 : 0
        TapAction {
          id: utX
          objectName: "updateToastSecondary"
          anchors.fill: parent
          anchors.margins: -8
          // The glyph alone does not say what it does; LATER names itself.
          accessibleLabel: updateToast.face === "ready" ? "LATER" : "Dismiss"
          onTriggered: updateToast.dismiss()
        }
      }
    }
  }

  // FFmpeg-missing download gate: the download is HELD backend-side before
  // anything is queued, because without FFmpeg the files come out degraded
  // (no FLAC extraction, no video conversion, no track-length repair, so
  // strict players can read 0:00). Fix it first, or knowingly continue.
  Rectangle {
    id: ffmpegBlockGate
    objectName: "ffmpegBlockGate"
    anchors.fill: parent
    visible: root.ffmpegBlocked
    color: "#cc06070e"
    MouseArea {
      anchors.fill: parent
      onClicked: {
        root.ffmpegBlocked = false
        waves.dismissDownloadFolderNudge()
      }
    }   // click-away cancels (no download)
    Rectangle {
      anchors.centerIn: parent
      width: 460
      implicitHeight: fbCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline
      MouseArea {
        anchors.fill: parent
      }   // a click on the card must not dismiss
      ColumnLayout {
        id: fbCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          wrapMode: Text.WordWrap
          text: "This download needs FFmpeg"
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          text: "FFmpeg isn't set up, so files would save degraded: FLAC stays wrapped in its stream container, videos aren't converted, and track lengths aren't repaired (strict players can show 0:00). Set it up in Settings with one click, then start the download again, or continue anyway with these limitations."
        }
        RowLayout {
          Layout.fillWidth: true
          Layout.topMargin: 4
          spacing: 12
          GateAction {
            showArrow: false
            label: "Set up FFmpeg"
            onClicked: {
              root.ffmpegBlocked = false
              waves.dismissDownloadFolderNudge()
              root.openFfmpegSetting()
            }
          }
          GateAction {
            objectName: "ffmpegGateContinue"
            showArrow: false
            neutral: true
            label: "Continue anyway"
            onClicked: {
              root.ffmpegBlocked = false
              waves.bypassFfmpegGate()
            }
          }
        }
      }
    }
  }

  // ====================================================================
  // Usage agreement, a non-dismissible gate shown the first time a user is
  // signed in. The only way past it is to acknowledge; the acceptance is
  // persisted (QSettings) so it appears once, not on every launch.
  // ====================================================================
  // termsVersion is the identity of the text below. It is stored with the
  // acceptance so a later revision can re-prompt only the users who agreed
  // to something older, and so the accepted wording is knowable after the
  // fact. Local only: nothing about the acceptance is ever reported.
  readonly property string termsVersion: "1.0"
  readonly property string termsVersionStamp: "Terms v1.0 (10 August 2026)"

  Settings {
    id: legalSettings
    category: "legal"
    property bool termsAccepted: false
    property string termsAcceptedVersion: ""
    property string termsAcceptedDate: ""
  }

  // The stored version is READ, not just written: an acceptance of an older
  // revision is not an acceptance of this one, so bumping termsVersion
  // re-prompts exactly the users whose stamp is older (or absent, the
  // pre-stamp acceptances). String compare on purpose: any difference from
  // the current version means "not these terms".
  readonly property bool termsCurrentAccepted: legalSettings.termsAccepted && legalSettings.termsAcceptedVersion === termsVersion

  Rectangle {
    id: termsGate
    anchors.fill: parent
    // Above the launch overlay (z 100000). Nothing outranks a gate that
    // has to be read and agreed to: at default z the launch wordmark was
    // painted straight across the terms card for the whole handover.
    z: 100001
    // ...and it is what the launch sequence reveals, riding the same dial
    // the interface normally rides (root.bootContentShown): the wordmark's
    // zoom fades directly into this card, with the app itself still
    // unpainted behind it. Agreement first, interface second.
    readonly property bool wanted: root.signedIn && setupSettings.ffmpegSetupDone && !root.termsCurrentAccepted
    visible: wanted && root.bootContentShown > 0
    opacity: root.bootContentShown
    color: "#f406070e"
    // Eat every click so nothing behind the gate is reachable; with no close
    // control and no outside-click handler, the gate cannot be dismissed.
    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
    }

    Rectangle {
      anchors.centerIn: parent
      width: 540
      // Never taller than the window: on a short window the card stops
      // growing and the terms body scrolls inside it instead of the
      // buttons being pushed off screen.
      implicitHeight: Math.min(termsCol.implicitHeight + 40, termsGate.height - 32)
      radius: 14
      color: root.surface2
      border.color: root.outline

      ColumnLayout {
        id: termsCol
        anchors.centerIn: parent
        width: parent.width - 40
        height: Math.min(implicitHeight, parent.height - 40)
        spacing: 13

        Text {
          Layout.fillWidth: true
          text: "Before you continue"
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
        }
        Flickable {
          id: termsBodyFlick
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredHeight: termsBody.implicitHeight
          Layout.minimumHeight: 60
          contentHeight: termsBody.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          ScrollBar.vertical: ScrollBar {
            // Tolerance, not a bare >: layout rounding leaves the
            // content a hair taller than the view and armed the
            // bar on a window with room to spare.
            policy: termsBodyFlick.contentHeight - termsBodyFlick.height > 1 ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
          }
          Text {
            id: termsBody
            textFormat: Text.PlainText
            // The gutter is reserved whether or not the bar is up:
            // sizing it off the bar's own visibility would feed the
            // wrap back into the height that decides it.
            width: termsBodyFlick.width - 14
            wrapMode: Text.WordWrap
            // lineHeight leading is not counted into implicitHeight
            // for the last line, which clipped it (and armed the
            // scrollbar) even with the whole card to spare.
            bottomPadding: 6
            color: root.textLo
            font.pixelSize: 13
            lineHeight: 1.3
            text: "Waves is a personal, non-commercial tool for accessing your own TIDAL account. By continuing, you agree that:\n\n" + "•  You will use Waves only for lawful, personal, non-commercial purposes, and only with content you are authorized to access.\n" + "•  You will not use Waves to infringe copyright or to reproduce, distribute, or pirate any content. Respect the rights of artists and rights-holders.\n" + "•  Your use of Waves may violate TIDAL's Terms of Service. You accept that risk and any consequences to your account, and you are responsible for complying with all laws that apply to you.\n" + "•  Waves is provided \"as is\", without warranty of any kind, and to the fullest extent permitted by law its developers and contributors accept no liability for any damages arising from it. See sections 15 and 16 of the AGPL-3.0.\n" + "•  You will indemnify and hold harmless the developers and contributors of Waves against any claim, loss or demand arising from your use of it or your breach of these terms.\n\n" + "Waves is not affiliated with, endorsed by, or sponsored by TIDAL. TIDAL is a trademark of its owner, used here only to identify the service Waves works with."
          }
        }
        // Privacy promise, emphasized, the closing note of the preamble.
        Rectangle {
          Layout.fillWidth: true
          implicitHeight: 1
          color: root.border1
        }
        Text { // guard:deliberate-richtext privacy-promise
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
          textFormat: Text.StyledText
          text: "Waves does not collect any information from its users and has no way of knowing how the application is used. " + "<font color=\"#3dff6e\">Privacy is the foundation of this application.</font>"
          color: root.textHi
          font.pixelSize: 13
          font.bold: true
          lineHeight: 1.3
        }
        RowLayout {
          Layout.fillWidth: true
          spacing: 10
          Rectangle {
            id: ackChk
            objectName: "termsAckCheck"
            property bool checked: false
            Layout.alignment: Qt.AlignTop
            implicitWidth: 20
            implicitHeight: 20
            radius: 5
            color: checked ? root.accent : "transparent"
            border.color: checked ? root.accent : root.outline
            border.width: 1.5
            Ico {
              anchors.centerIn: parent
              visible: ackChk.checked
              name: "check"
              color: root.accentText
              size: 13
              bold: 8
            }
            TapAction {
              anchors.fill: parent
              accessibleLabel: "I have read and agree to these terms."
              role: Accessible.CheckBox
              checkable: true
              checked: ackChk.checked
              focusRadius: 5
              onTriggered: ackChk.checked = !ackChk.checked
            }
          }
          Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: "I have read and agree to these terms."
            color: root.textHi
            font.pixelSize: 13
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: ackChk.checked = !ackChk.checked
            }
          }
        }
        GateAction {
          objectName: "termsAckAction"
          label: "ACKNOWLEDGE & AGREE"
          enabled: ackChk.checked
          opacity: ackChk.checked ? 1 : 0.4
          // freshSetup: the opt-in prompt that follows this gate reads
          // differently for a first run than for a user who updated in.
          onClicked: if (ackChk.checked) {
            // Record WHICH terms were agreed to, not just that some
            // were: a future revision re-prompts only the users
            // whose stored version is older.
            legalSettings.termsAcceptedVersion = root.termsVersion
            legalSettings.termsAcceptedDate = new Date().toISOString().slice(0, 10)
            legalSettings.termsAccepted = true
            setupSettings.updatePromptFresh = true
          }
        }
        Text {
          Layout.fillWidth: true
          horizontalAlignment: Text.AlignHCenter
          textFormat: Text.PlainText
          text: root.termsVersionStamp
          color: root.textDim
          font.pixelSize: 11
        }
      }
    }
  }

  // ====================================================================
  // The library claim, opened up. A Download button reading DOWNLOADED
  // because the LIBRARY SCAN matched a folder (not because Waves has a
  // record of downloading it) stays clickable, and lands here.
  //
  // WHY THIS EXISTS: the match is inferred from tags, so it can be wrong,
  // and a wrong one must never be silent and terminal: a button that says
  // DOWNLOADED, does nothing, and explains nothing. This says what was
  // matched, shows where it is so the user can judge for themselves, and
  // keeps DOWNLOAD ANYWAY one click away. Nothing is remembered, because
  // DOWNLOAD ANYWAY is one-shot: the click starts the download, and from
  // there the live queue state drives the button.
  //
  // Detection must never prevent a download the user could otherwise make;
  // this is the escape hatch that keeps that true, for an album and for a
  // single track alike. The two differ only in wording and in which download
  // ANYWAY makes: an album needs a claim override so the bulk gate does not
  // then skip every track it contains, a track was never gated to begin with.
  // ====================================================================
  Rectangle {
    id: libraryClaimGate
    objectName: "libraryClaimGate"
    // Same reason as exitGate: a Drawer paints in the window's overlay
    // layer, so a gate parented to the page sits under it whatever its z.
    parent: Overlay.overlay
    anchors.fill: parent
    z: 1200
    property bool shown: false
    property string albumId: ""
    property string albumTitle: ""
    property string folder: ""
    // "album" or "track". Picks the wording and the download the ANYWAY
    // click makes; everything else about the conversation is the same.
    property string kind: "album"
    // "claim" (a library tag match, the original conversation) or
    // "owned" (a record of a download Waves made; REDOWNLOAD re-fetches).
    property string mode: "claim"
    property var card: null
    readonly property bool isTrack: kind === "track"
    readonly property bool isOwned: mode === "owned"
    visible: opacity > 0
    opacity: shown ? 1 : 0
    Behavior on opacity {
      NumberAnimation {
        duration: 260
        easing.type: Easing.OutCubic
      }
    }
    color: "#cc06070e"
    function proceed() {
      var aid = libraryClaimGate.albumId
      var wasTrack = libraryClaimGate.isTrack
      libraryClaimGate.shown = false
      if (aid === "")
        return
      if (libraryClaimGate.isOwned) {
        // Force first, then start the normal per-kind download: the
        // override is what makes the job actually fetch owned tracks.
        waves.registerRedownload(aid)
        if (libraryClaimGate.card)
          root.browseCardDownload(libraryClaimGate.card)
        return
      }
      // A single track needs no override: the bulk claim gate rides only
      // on collection jobs, so one track asked for by name has never been
      // skippable and downloadTrack really downloads.
      if (wasTrack) {
        waves.downloadTrack(aid)
        return
      }
      // "Anyway" registers a claim override first: with the bulk claim
      // gate on, a plain downloadAlbum of a fully-claimed album would
      // skip every track it contains and report done having fetched
      // nothing, which is exactly what this click just declined.
      waves.downloadAlbumAnyway(aid)
    }
    function reveal() {
      var p = libraryClaimGate.folder
      libraryClaimGate.shown = false
      if (p !== "")
        waves.revealLibraryAlbum(p)
    }
    MouseArea {
      anchors.fill: parent
      onClicked: libraryClaimGate.shown = false
    }
    Rectangle {
      anchors.centerIn: parent
      width: 480
      implicitHeight: lcgCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline
      MouseArea {
        anchors.fill: parent
      }   // a click on the card must not dismiss
      ColumnLayout {
        id: lcgCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          horizontalAlignment: Text.AlignHCenter
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          wrapMode: Text.WordWrap
          text: libraryClaimGate.isOwned ? "You already downloaded this" : "This looks like it is already in your library"
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          // A track match names a file, not a folder, and the folder
          // line below is then the album it was found sitting in,
          // which is also the evidence the identity was proven from.
          // The owned mode is a different conversation: a record of
          // a download Waves made, not a guess to be judged.
          // Each promise below is conditional because the behaviour
          // is: with "Skip existing" on nothing on disk is ever
          // replaced, with it off a same-named file of the same
          // track is (that is what the setting asks for). Either
          // way a Dolby Atmos file is never replaced by a stereo
          // download; the engine steps aside to a numbered name.
          text: libraryClaimGate.isOwned ? ((libraryClaimGate.albumTitle !== "" ? "Waves downloaded “" + libraryClaimGate.albumTitle + "” itself, so this is a record, not a guess." : "Waves downloaded this itself, so this is a record, not a guess.") + (libraryClaimGate.isTrack ? " Redownloading fetches it fresh and replaces the copy Waves wrote," : " Redownloading fetches every track fresh and replaces the copies Waves wrote,") + " including a same-named file it cannot tell apart from its own." + " A Dolby Atmos file is never replaced by a stereo download; that lands beside it.") : ((libraryClaimGate.isTrack ? (libraryClaimGate.albumTitle !== "" ? "A file in your music library matches “" + libraryClaimGate.albumTitle + "”." : "A file in your music library matches this track.") : (libraryClaimGate.albumTitle !== "" ? "A folder in your music library matches “" + libraryClaimGate.albumTitle + "”." : "A folder in your music library matches this album.")) + " The match is made from tags, so it can be wrong." + (waves.skipExistingFiles ? " Downloading again never replaces a file already on disk: a track already" + " sitting at its exact name is kept, anything else gets its own copy beside it." : " With “Skip existing” turned off, downloading again replaces a same-named file" + " unless Waves can tell it is a different track. A Dolby Atmos file is never" + " replaced by a stereo download."))
        }
        // The evidence, so the user can judge the match rather than
        // take the button's word for it.
        Text {
          visible: libraryClaimGate.folder !== ""
          textFormat: Text.PlainText
          Layout.fillWidth: true
          horizontalAlignment: Text.AlignHCenter
          elide: Text.ElideMiddle
          color: root.textDim
          font.family: root.mono
          font.pixelSize: 12
          text: libraryClaimGate.folder
        }
        // This gate is the only one with no explicit dismiss button
        // (three CTAs crowd the row), so the way out is spelled out.
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
          color: root.textDim
          font.pixelSize: 12
          text: "Click away to leave it alone."
        }
        RowLayout {
          Layout.alignment: Qt.AlignHCenter
          Layout.topMargin: 4
          spacing: 12
          SpecBtn {
            primary: true
            label: "SHOW IN FOLDER"
            visible: libraryClaimGate.folder !== ""
            onClicked: libraryClaimGate.reveal()
          }
          SpecBtn {
            label: libraryClaimGate.isOwned ? "REDOWNLOAD" : "DOWNLOAD ANYWAY"
            onClicked: libraryClaimGate.proceed()
          }
        }
      }
    }
  }

  // ====================================================================
  // Update opt-in prompt, the last step of the first-run chain (login >
  // FFmpeg > terms > this) and shown once to existing installs that
  // predate it. Lands directly after the terms gate's privacy promise on
  // purpose: here is the one optional outbound connection, asked for.
  // Either button answers it for good; a click-away re-asks next launch,
  // then stops.
  // ====================================================================
  Rectangle {
    id: updateOptInGate
    objectName: "updateOptInGate"
    // Same reason as exitGate: a Drawer paints in the window's overlay
    // layer, so a gate parented to the page sits under it whatever its z.
    parent: Overlay.overlay
    anchors.fill: parent
    // Above the video overlay (999) and the peek card (990): a first-run
    // prompt must never paint underneath a playing video.
    z: 1200
    // termsCurrentAccepted, not the bare boolean: during a terms-revision
    // re-prompt this card must wait behind the terms gate, never beside it.
    readonly property bool shouldShow: root.signedIn && setupSettings.ffmpegSetupDone && root.termsCurrentAccepted && bootOverlay.done && !ffmpegGate.visible && !setupSettings.updatePromptAnswered && setupSettings.updatePromptDismissals < 2 && !sessionDismissed && !autoUpdateOn
    // Rather than pop: the card slides up from below the frame while this
    // scrim dims the app behind it, and both reverse on dismissal.
    visible: opacity > 0
    opacity: shouldShow ? 1 : 0
    Behavior on opacity {
      NumberAnimation {
        duration: 520
        easing.type: Easing.OutCubic
      }
    }
    color: "#cc06070e"
    // Read once at startup: while this gate can be on screen the only
    // in-app write to auto_update is the gate's own accept.
    readonly property bool autoUpdateOn: waves.wavesPref("auto_update") === true
    property bool sessionDismissed: false
    // Set by the terms gate's acknowledge, so the copy can address a
    // fresh setup instead of a user who updated into this prompt.
    // Persisted (setupSettings): a click-away re-asks NEXT LAUNCH, and a
    // session-only flag would greet that same fresh install with the
    // "you have been running without update checks" veteran copy.
    readonly property bool freshSetup: setupSettings.updatePromptFresh
    function answer(enabled) {
      setupSettings.updatePromptAnswered = true
      waves.resolveUpdateOptIn(enabled)
    }
    MouseArea {
      anchors.fill: parent
      onClicked: {
        updateOptInGate.sessionDismissed = true
        setupSettings.updatePromptDismissals++
      }
    }
    Rectangle {
      // 500, not the other gates' 460: sized so the body sets as three
      // even lines (the terms gate already runs wider at 540).
      anchors.centerIn: parent
      width: 500
      implicitHeight: uoCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline
      // The slide itself: parked below the bottom edge until the gate
      // opens, then rides up to centre as the scrim dims.
      anchors.verticalCenterOffset: updateOptInGate.shouldShow ? 0 : updateOptInGate.height / 2 + height
      Behavior on anchors.verticalCenterOffset {
        NumberAnimation {
          duration: 520
          easing.type: Easing.OutCubic
        }
      }
      MouseArea {
        anchors.fill: parent
      }   // a click on the card must not dismiss
      ColumnLayout {
        id: uoCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          horizontalAlignment: Text.AlignHCenter
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          wrapMode: Text.WordWrap
          text: updateOptInGate.freshSetup ? "Stay current with Waves" : "Want to hear about updates?"
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          text: (updateOptInGate.freshSetup ? "Waves updates often, and most updates fix problems you would otherwise run into. " : "Waves never asked before, so you have been running without update checks. ") + "A once-a-day check tells you when a new version is out. Nothing is downloaded or installed unless you choose it."
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
          color: root.textDim
          font.pixelSize: 12
          lineHeight: 1.3
          text: "You can change this any time in Settings."
        }
        RowLayout {
          Layout.alignment: Qt.AlignHCenter
          Layout.topMargin: 4
          spacing: 12
          SpecBtn {
            primary: true
            label: "TURN ON UPDATE CHECKS"
            onClicked: updateOptInGate.answer(true)
          }
          SpecBtn {
            label: "NOT NOW"
            onClicked: updateOptInGate.answer(false)
          }
        }
      }
    }
  }

  // Exit warning: the window close was vetoed (onClosing) because downloads
  // are still running. KEEP DOWNLOADING cancels the exit; EXIT ANYWAY
  // re-closes for real. The checkbox persists on either button; a click
  // away is treated as keeping the downloads, without persisting it.
  Rectangle {
    id: exitGate
    objectName: "exitGate"
    // A Drawer (the queue) lives in the window's OVERLAY layer, which
    // paints over ordinary content whatever z that content carries, so a
    // gate parented to the page was masked by the drawer's dim while the
    // queue was open. Joining the same layer is what actually puts it on
    // top; the z below then orders it inside that layer.
    parent: Overlay.overlay
    anchors.fill: parent
    // Above the video overlay (999): the close veto opens this gate, and
    // with a video full-screen a default z would paint it underneath,
    // leaving the window looking un-closable.
    z: 1200
    visible: open
    property bool open: false
    // Lets the EXIT ANYWAY re-close pass the onClosing veto. Reset when
    // the gate opens so a cancelled exit re-arms the warning.
    property bool confirmed: false
    onOpenChanged: if (open) {
      confirmed = false
      exitSkip.checked = false
    }
    color: "#cc06070e"
    MouseArea {
      anchors.fill: parent
      onClicked: exitGate.open = false
    }
    Rectangle {
      // 420: narrower than the info-heavy gates, this one is a short
      // question and the body still sets as two lines.
      anchors.centerIn: parent
      width: 420
      implicitHeight: exCol.implicitHeight + 40
      radius: 14
      color: root.surface2
      border.color: root.outline
      MouseArea {
        anchors.fill: parent
      }   // a click on the card must not dismiss
      ColumnLayout {
        id: exCol
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 14
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          horizontalAlignment: Text.AlignHCenter
          color: root.textHi
          font.pixelSize: 18
          font.bold: true
          wrapMode: Text.WordWrap
          text: "Exit while downloading?"
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
          color: root.textLo
          font.pixelSize: 13
          font.bold: true
          lineHeight: 1.3
          // The 0 case is reachable: the last download can finish
          // while this gate is up. The copy must not read "0
          // downloads are still running." at that moment.
          text: root.activeQueueCount === 0 ? "All downloads finished." : root.activeQueueCount === 1 ? "A download is still running." : root.activeQueueCount + " downloads are still running."
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
          color: root.textLo
          font.pixelSize: 13
          lineHeight: 1.3
          Layout.topMargin: -8   // the pair reads as one statement, not two paragraphs
          text: root.activeQueueCount === 0 ? "It is safe to exit now." : "Exiting now ends " + (root.activeQueueCount === 1 ? "it" : "them") + ", and unfinished tracks will need to be downloaded again."
        }
        RowLayout {
          Layout.alignment: Qt.AlignHCenter
          Layout.topMargin: 4
          spacing: 12
          SpecBtn {
            primary: true
            label: "KEEP DOWNLOADING"
            onClicked: {
              if (exitSkip.checked)
                setupSettings.exitWarnMuted = true
              exitGate.open = false
            }
          }
          SpecBtn {
            danger: true
            label: "EXIT ANYWAY"
            onClicked: {
              if (exitSkip.checked)
                setupSettings.exitWarnMuted = true
              exitGate.confirmed = true
              exitGate.open = false
              root.close()
            }
          }
        }
        Row {
          // "Don't warn me again" row: catDlGate grammar, centred to
          // match this card's centered text; below the buttons so the
          // choice reads first and the escape hatch last.
          Layout.alignment: Qt.AlignHCenter
          spacing: 8
          Check {
            id: exitSkip
            objectName: "exitSkipCheck"
            anchors.verticalCenter: parent.verticalCenter
            accessibleLabel: "Don't warn me again"
            onToggled: checked = !checked
          }
          Text {
            textFormat: Text.PlainText
            anchors.verticalCenter: parent.verticalCenter
            text: "Don't warn me again"
            color: root.textLo
            font.pixelSize: 13
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: exitSkip.checked = !exitSkip.checked
            }
          }
        }
      }
    }
  }

  // ==== Open-water launch sequence ("Z FILL") ====
  // The app opens on its own water video, bright (scrim held at 0.55) with
  // the WAVES wordmark centred and the running version tucked at its
  // bottom-right. Once the session resolves and the landing has content
  // (2s cap), a progress bar completes over the version and drains away,
  // then the wordmark zooms toward the viewer as the water dims to its
  // resting scrim and the interface fades in. One video instance start to
  // finish, so the handover is seamless by construction.
  Item {
    id: bootOverlay
    anchors.fill: parent
    z: 100000
    visible: !done
    property bool started: false
    property bool done: false

    // Input shield. The interface underneath hides by opacity alone, so
    // without this it stays clickable and hoverable while invisible: a
    // click on the launch water could land on a preview control and start
    // full-volume audio, and the hand cursor would roam over buttons nobody
    // can see. Eats clicks, hover, and wheel, and keeps the
    // plain arrow cursor, until the reveal starts painting the content.
    // Visibility-gated as well: a MouseArea claims the cursor even while
    // disabled, so a boot that never reaches done would otherwise cost
    // every button its pointing hand for the whole session; an invisible
    // one claims nothing.
    MouseArea {
      id: bootShield
      anchors.fill: parent
      visible: enabled
      enabled: root.bootContentShown === 0
      hoverEnabled: enabled
      acceptedButtons: Qt.AllButtons
      onWheel: function (w) {
        w.accepted = true
      }
    }

    function maybeStart() {
      if (started || done)
        return
      if (!waves.sessionResolved)
        return
      if (root.signedIn && root.browseSections.length === 0)
        return
      started = true
      bootSeq.start()
    }
    Component.onCompleted: maybeStart()
    Connections {
      target: waves
      function onSessionResolvedChanged() {
        bootOverlay.maybeStart()
      }
      function onLoggedInChanged() {
        bootOverlay.maybeStart()
      }
    }
    Connections {
      target: root
      // Held handover: the landing's first payload arrived, re-check the
      // gate (the build it just started re-holds until the shelves are
      // in, so the reveal still lands on a finished page).
      function onBrowseSectionsChanged() {
        bootOverlay.maybeStart()
        if (bootOverlay.handoverHeld)
          bootOverlay.handover()
      }
      // Held handover: the landing finished assembling, go now.
      function onBrowseBuildingChanged() {
        if (bootOverlay.handoverHeld && !root.browseBuilding)
          bootOverlay.handover()
      }
      // Held handover: the fetch failed; nothing further is coming, so
      // reveal the error state rather than sit on the wordmark.
      function onBrowseErrorChanged() {
        if (bootOverlay.handoverHeld && root.browseError)
          bootOverlay.handover()
      }
    }
    // Readiness cap: never hold the launch look longer than this.
    Timer {
      interval: 2000
      running: true
      onTriggered: {
        if (!bootOverlay.started) {
          bootOverlay.started = true
          bootSeq.start()
        }
      }
    }

    // handover gate
    // Covering the Browse landing's assembly is the whole point of this
    // sequence, so the opening frame holds until the shelves have finished
    // incubating. Without the gate the overlay lifts on its own schedule
    // and the page drops in shelf by shelf, as if it were scrolling
    // itself. Capped, so a stalled
    // or endless build can never pin the launch screen. Everything that
    // signals the handover (the version drain, then the zoom) lives in
    // bootHandover, downstream of this gate, so with respect to each
    // other their timing is exactly what it would be with no gate at all.
    property bool handoverHeld: false
    function handover() {
      if (done)
        return
      // Data still in flight: signed in but the landing has nothing to
      // reveal yet (a slow token check or first fetch outran the opening
      // frame; the readiness cap below starts the sequence regardless).
      // Hold here, wordmark and version still up, exactly the frame the
      // bootSeq comment says any wait belongs on; the payload arriving,
      // the fetch erroring, or the cap releases it. Without this leg the
      // gate would only cover the shelf assembly, and a slow login would
      // reveal the bare "Reading the wire…" landing.
      if (root.signedIn && root.browseSections.length === 0 && !root.browseError && !handoverCap.expired) {
        handoverHeld = true
        return
      }
      if (root.browseBuilding && !handoverCap.expired) {
        // Shelves going up again after the count went quiet make that
        // quiet stale: neither they nor their cards were in it, so the
        // third leg has to be shown quiet once more, for THIS build.
        incubationQuietPoll.quietRuns = 0
        handoverHeld = true
        return
      }
      // Third leg: the incubation controller's own count. Boot-paced
      // incubation (app.py's _BootPacedIncubation, which paces the
      // landing build so it cannot freeze the boot water for ~300 ms
      // stretches) completes the landing's CARD loaders after the veil count has
      // already settled, so browseBuilding alone no longer promises a
      // finished page. The controller's count covers everything still
      // assembling, but one reading of it decides nothing: it blips to
      // zero between batches, and a reading taken HERE is the least
      // trustworthy of all. This leg is normally reached from the veil
      // falling, which happens inside the last counted loader's `loaded`
      // handler, after the engine has already dropped that loader from
      // the count and before the shelves' card loaders exist to join it,
      // so a zero at this instant is exactly what a page that has not
      // begun its cards looks like: reading it here would reveal onto
      // the cards popping in. So the count is not read on this path
      // at all. The hold is taken, and only the poll below, quiet on two
      // readings in a row, can lift it; the cap the other legs answer to
      // ends the hold regardless of what the count ever says.
      if (root.signedIn && !root.browseError && !incubationQuietPoll.settled && !handoverCap.expired) {
        handoverHeld = true
        // A poll already counting is left running: ITS readings are the
        // consecutive ones. Re-arming on every re-entry (each payload,
        // each veil edge) would keep resetting the count instead.
        if (!incubationQuietPoll.running) {
          incubationQuietPoll.quietRuns = 0
          incubationQuietPoll.restart()
        }
        return
      }
      handoverHeld = false
      handoverCap.stop()
      incubationQuietPoll.stop()
      bootHandover.start()
    }
    // The one place the incubation count is read: on a fixed cadence, and
    // only while the third leg holds. Two consecutive quiet readings is
    // the bar because a single zero can be the gap between batches (the
    // next one registers within a pacing tick or two), while a gap wide
    // enough to swallow two readings 200 ms apart is not a gap, it is a
    // finished page. quietRuns IS that record, so it is what a later build
    // resets (see the second leg), and `settled` is only ever read by the
    // leg it releases.
    Timer {
      id: incubationQuietPoll
      property int quietRuns: 0
      readonly property bool settled: quietRuns >= 2
      interval: 200
      repeat: true
      onTriggered: {
        if (!bootOverlay.handoverHeld || bootOverlay.done) {
          stop()
          return
        }
        if (waves.bootIncubationBusy()) {
          quietRuns = 0
          return
        }
        if (++quietRuns >= 2) {
          stop()
          bootOverlay.handover()
        }
      }
    }
    Timer {
      id: handoverCap
      property bool expired: false
      // Sized for the data wait (login round-trip + first landing fetch
      // on a slow network), not just the shelf assembly: the build leg
      // has its own 800ms stall guard (browseBuildGuard), so only a
      // genuinely dead network ever rides this cap to the end, and even
      // then the launch screen cannot be pinned past it.
      interval: 8000
      onTriggered: {
        expired = true
        bootOverlay.handover()
      }
    }

    // the wordmark (typography as in WelcomeBanner)
    Item {
      id: bootTitle
      property real shown: 0   // faded up by bootIntro
      property real zoom: 1
      anchors.fill: parent
      scale: bootTitle.zoom
      // One Text per glyph, tracked by Row spacing rather than
      // font.letterSpacing: no trailing space means centerIn really
      // centres the glyph run, and the W (which the mono face
      // compresses to fit its fixed cell) can be stretched back out
      // on its own without touching its advance.
      Row {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 2
        spacing: 28
        Repeater {
          model: ["W", "A", "V", "E", "S"]
          Text {
            id: gs
            textFormat: Text.PlainText
            text: modelData
            font.family: root.mono
            font.pixelSize: 126
            font.bold: true
            color: "#0a160d"
            opacity: 0.9 * bootTitle.shown   // shadow
            transform: Scale {
              origin.x: gs.width / 2
              xScale: gs.text === "W" ? 1.08 : 1
            }
          }
        }
      }
      Row {
        id: bootMark
        anchors.centerIn: parent
        spacing: 28
        Repeater {
          model: ["W", "A", "V", "E", "S"]
          Text {
            id: gf
            textFormat: Text.PlainText
            text: modelData
            font.family: root.mono
            font.pixelSize: 126
            font.bold: true
            // Softened off flat white: full textHi at this size
            // read harsh against the dark water.
            color: root.textHi
            opacity: 0.85 * bootTitle.shown
            transform: Scale {
              origin.x: gf.width / 2
              xScale: gf.text === "W" ? 1.08 : 1
            }
          }
        }
      }
    }

    // version readout: read once at launch (set and forget)
    // Outside bootTitle so it never scales with the zoom; tucked at the
    // bottom-right of the wordmark with slight padding.
    Text {
      id: bootVer
      property real shown: 0   // faded up by bootIntro, with the wordmark
      textFormat: Text.PlainText
      text: "v" + waves.appVersion
      font.family: root.mono
      font.pixelSize: 16
      font.bold: true
      font.letterSpacing: 7
      color: root.accent
      // Right edge aligned under the S: the per-glyph Row carries no
      // trailing spacing, so its right edge IS the S's right edge.
      x: bootOverlay.width / 2 + bootMark.width / 2 - width
      // Tucked just under the wordmark's baseline. The metrics box runs
      // a descender's worth below the caps, and "WAVES" has none, so
      // sitting at its bottom edge left the readout stranded well clear
      // of the glyphs; pull back up to hug them.
      y: bootOverlay.height / 2 + bootMark.height / 2 - 27
      opacity: 0.85 * shown
    }

    // The version's exit, built on the progress bars' cells: a bar
    // completes over the text, drains to dim, then empties out.
    Timer {
      id: bootBlk
      interval: 36
      repeat: true
      property int tick: 0
      property string base: ""
      // How long one full drain lasts, in ms. The walk is three passes
      // over the cells (fill, dim, empty) plus the closing tick that
      // stops the timer and clears the readout, one tick per cell, so
      // its length follows the version string and is never a constant.
      // bootHandover waits exactly this before the zoom: a fixed pause
      // was shorter than the walk (700ms against 792ms for "v0.1.11"),
      // so the last cells were still emptying once the zoom had begun.
      readonly property int runMs: interval * (3 * base.length + 1)
      onTriggered: {
        tick += 1
        var m = base.length
        var out = ""
        for (var i = 0; i < m; ++i) {
          if (tick > 2 * m + i)
            out += " "
          else if (tick > m + i)
            out += "░"
          else if (tick > i)
            out += "█"
          else
            out += base[i]
        }
        bootVer.text = out
        // The zoom starts HERE, welded to the walk actually finishing.
        // A wall-clock pause sized to runMs cannot hold: these ticks
        // ride the GUI thread, so any boot work (the landing
        // assembling) slips them, leaving the readout still draining
        // while the interface fades up underneath. The drain's own last
        // tick can never be early or late relative to itself.
        if (tick > 3 * m) {
          stop()
          tick = 0
          bootVer.shown = 0
          bootZoom.start()
        }
      }
    }

    // The opening is a fade-up, not a cut: the wordmark and the version
    // rise out of the dark together, on one curve, so they read as a
    // single composed mark rather than two arrivals. Deliberately NOT
    // part of bootSeq: that sequence waits on the session and the landing
    // (up to 2s), and the opening frame must never sit blank while it
    // does, so the fade runs from the first frame regardless.
    ParallelAnimation {
      id: bootIntro
      running: true
      NumberAnimation {
        target: bootTitle
        property: "shown"
        from: 0
        to: 1
        duration: 900
        easing.type: Easing.OutCubic
      }
      NumberAnimation {
        target: bootVer
        property: "shown"
        from: 0
        to: 1
        duration: 900
        easing.type: Easing.OutCubic
      }
      // A first landing that arrived mid-fade waits here (see
      // onBrowseLoaded): applying it during the fade cost the fade its
      // frames. The composed mark is now still, so the async build gets
      // the calm stretch before the handover to itself.
      onFinished: {
        if (root._browseParked && root.browseSections.length === 0) {
          var parked = root._browseParked
          root._browseParked = null
          root.applyBrowseLanding(parked)
        }
      }
    }

    SequentialAnimation {
      id: bootSeq
      // Long enough for the fade-up (~0.9s) to finish and the composed
      // frame to settle before anything starts leaving. A MINIMUM by
      // design, not a wait to shave: users sit here long enough to see
      // the whole animation and read the version for a beat; only waits
      // BEYOND this minimum are load-dependent (the handover gate below).
      PauseAnimation {
        duration: 1900
      }   // hold the opening frame; the water fades in under it
      // Any wait for the landing happens HERE, on the opening frame with
      // the wordmark and version still up, never after the version has
      // drained: that readout emptying out reads as "about to hand over"
      // and must stay welded to the zoom that follows it.
      ScriptAction {
        script: {
          handoverCap.restart()
          bootOverlay.handover()
        }
      }
    }

    // Handover = start the version drain; its last tick starts bootZoom
    // (see bootBlk.onTriggered), so nothing of the readout is ever left
    // on screen when the zoom and the interface reveal begin, however
    // busy the GUI thread was during the walk.
    SequentialAnimation {
      id: bootHandover
      // The drain is also where the interface gets painted for the
      // first time, invisibly, so the zoom that follows it is not the
      // frame that pays for it (see root.bootWarming).
      ScriptAction {
        script: {
          root.bootWarming = true
          bootBlk.base = bootVer.text
          bootBlk.restart()
        }
      }
    }
    SequentialAnimation {
      id: bootZoom
      // Tight zoom: the wordmark is gone in ~0.7s and the interface only
      // starts appearing once the title is mostly faded, so text never
      // lingers over visible UI.
      ParallelAnimation {
        NumberAnimation {
          target: bootTitle
          property: "zoom"
          to: 2.4
          duration: 700
          easing.type: Easing.InCubic
        }
        NumberAnimation {
          target: bootTitle
          property: "shown"
          to: 0
          duration: 550
          easing.type: Easing.InQuad
        }
        NumberAnimation {
          target: root
          property: "bootScrimLevel"
          to: 0.93
          duration: 800
          easing.type: Easing.InOutSine
        }
        SequentialAnimation {
          PauseAnimation {
            duration: 350
          }
          NumberAnimation {
            target: root
            property: "bootContentShown"
            to: 1
            duration: 620
            easing.type: Easing.InOutSine
          }
        }
      }
      ScriptAction {
        script: {
          // Pin the final values (the overlay never runs again).
          root.bootScrimLevel = 0.93
          root.bootContentShown = 1
          bootOverlay.done = true
          // The launch look is over: open the incubation throttle
          // that kept the boot water smooth while the landing
          // assembled (app.py's _BootPacedIncubation).
          waves.bootRevealed()
          // A revalidate that landed during the reveal waited here.
          // Applied now, with done set, it takes the ordinary
          // in-place refresh path: no veil, nothing to watch.
          if (root._browseParked) {
            var parked = root._browseParked
            root._browseParked = null
            root.applyBrowseLanding(parked)
          }
        }
      }
    }
  }
}

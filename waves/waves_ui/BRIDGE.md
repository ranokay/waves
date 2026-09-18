# The QML/Python bridge

`WavesBridge` (backend.py) is exposed to QML as the context property
`waves`. QML calls its `@Slot`-decorated methods; the bridge answers by
emitting signals, which Main.qml consumes in one big
`Connections { target: waves }` block. Because slots run their blocking work
on thread pools and emit from worker threads, Qt delivers every signal on
the GUI thread (queued connection); QML handlers never see a race.

The signal declarations in backend.py carry inline comments with the exact
payload shapes. This file is the map of which signal belongs to which
feature.

## Session and status

| Signal                                                                                             | Fires when                                                                                                    |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `loggedInChanged`                                                                                  | Login/logout completes (property `loggedIn`)                                                                  |
| `sessionResolvedChanged`                                                                           | The restored session finishes resolving (property `sessionResolved`)                                          |
| `statusChanged`                                                                                    | The status-bar text changes                                                                                   |
| `busyChanged`                                                                                      | A blocking operation starts/ends                                                                              |
| `loginUrlReady(url)`                                                                               | The browser-login URL is ready to open                                                                        |
| `backRequested`                                                                                    | The platform back gesture (macOS trackpad swipe) asks to navigate back                                        |
| `motionBgChanged`                                                                                  | The motion-background preference flipped; Main.qml re-reads it                                                |
| `confirmCategoryDlChanged`                                                                         | The "confirm DOWNLOAD ALL on a Browse category" preference flipped (property `confirmCategoryDl`)             |
| `settingsPersistedExternally`                                                                      | Settings were saved by something other than the Settings page (a dialog, a recovery); the page re-reads       |
| `forwardRequested`                                                                                 | The mouse forward button asks to navigate forward (the back button fires `backRequested`)                     |
| `hoverMotionChanged` / `artHoverTiltChanged` / `videoHoverPeekChanged`                             | The matching motion preference flipped (`setWavesPref`); the surfaces re-read it                              |
| `diagnosticsExported(path)`                                                                        | A diagnostics export finished (`""` = failed)                                                                 |
| `appleStatusChanged`                                                                               | A save moved `apple_enabled` or the session; Settings re-reads `appleStatus()`; search clears when off        |
| `appleSetupRequested(reason)`                                                                      | Apple needs setup (`setup` on enable, `cookies` on a pre-setup download click); Main deep-links to the wizard |
| `setupRequested()`                                                                                 | Settings -> Providers -> "Set up providers" asks to re-open the provider welcome surface as a page            |
| `appleRuntimeStatusChanged` / `appleRuntimeProgress(pct)` / `appleRuntimeStateChanged(state, msg)` | The managed-Apple-runtime install/pull and sign-out lifecycle; Settings re-reads `appleSetupState()`          |

The provider cards' action pills dispatch through one slot, not per-provider
handlers: `providerAction(providerId, actionKey)` runs the key the schema
carried (`<provider id>_<verb>`). The generic verbs run through the provider
seam (`signin` starts the provider's login flow; `signout` runs its sign-out
or the app-level flow registered for it), and bridge-owned verbs (Apple's
runtime management) come from the registry built where the providers are
wired. `appleStatus()` answers `{state, word, actions}` — the same action
list the schema bakes — so a live light flip moves its pills with it.

The header's per-provider marks come from two answer-only slots, both
composed from the descriptors so a third provider needs no QML edit
(issue #223). `providerLights()` answers `[{id, name, state, word}]`, one
entry per provider with a status to report: a session-kind provider's
sign-in state (`signed_in` / `signed_out`, worded with the card's own
"Signed in" / "Signed out") or a setup-kind provider's setup light (Apple's
five states, `off` contributing none). The QML renders a dot per entry — the
colour is the shared status-light vocabulary in `qml/StatusLight.js` — and
re-reads on `loggedInChanged` / `appleStatusChanged`; sign-out lives on the
TIDAL card, never in the header. `browseNav()` answers `{available,
signed_in}`: Browse exists while a configured provider declares
`Capability.BROWSE` and is hidden when none does (never a permanently blank
tab), and `signed_in` is the live session of the browse-capable provider
whose pages fill the pane (the first in registry order), which the landing
pane offers its sign-in call to action for.

A provider's sign-in steps component (TIDAL's browser/paste pair) is a QML
component, so `providerSignInSteps()` answers the ids this build ships steps
for, registered where the providers are wired. The surface opens a
provider's steps when it has them and its cards otherwise; `signInRequested`
carries the provider whose sign-in the surface is showing.

The welcome surface's cards come from `providerCards()`: one entry per
registered provider with its descriptor identity (id/name/logo), its
`summary` (the one-line capability truth) and `action` (the provider's own
action words — a setup for Apple, a sign-in for TIDAL), plus `state`/`word`
from the same light composer as the header's marks ("" when the provider has
nothing to report, e.g. Apple switched off). The surface re-reads the list
at boot, when the surface opens and on the same flips as the lights, so a
card never states a stale account state (issue #219).

`appleSetupRequested(reason)` carries the wizard step a pre-setup click was
missing: `"cookies"` (no account yet — the cookies/wrapper tier) or
`"runtime"` (no fetch binary), or `"setup"` / `""` for the wizard's top. The
Apple wizard marks the named step in place, and SKIP FOR NOW leaves the page
for Search with Apple still enabled.

## Search, artist pages, library

| Signal                                                     | Fires when                                                                                                                                                                                                                                                                                        |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `searchResults(payload)`                                   | Search or a pasted TIDAL/Apple Music link finishes; TIDAL rows use the top-level per-kind lists and enabled Apple search adds the same shape under `apple`, plus `apple.error` with the provider's honest words when that fetch failed (empty on success; the group head renders it with a RETRY) |
| `albumTracksLoaded(albumId, tracks)`                       | An album's ordered track list arrives (album expansion)                                                                                                                                                                                                                                           |
| `artistLoaded(payload)`                                    | An artist page (bio, discography, top tracks) is ready                                                                                                                                                                                                                                            |
| `artistMetaLoaded(artistId, popularity)`                   | Late-arriving artist metadata                                                                                                                                                                                                                                                                     |
| `playlistTracksLoaded(playlistId, tracks)`                 | A playlist's ordered track list arrives (playlist expansion); empty on failure                                                                                                                                                                                                                    |
| `artistLoadFailed(artistId)`                               | An artist page could not load and nothing is cached; clears the Back-restore latch so history recording continues                                                                                                                                                                                 |
| `libraryLoaded(source, category, items, hasMore)`          | First page of one My Music source's shelf category (replace); `source` is a provider id (issue #259)                                                                                                                                                                                              |
| `libraryMore(source, category, items, hasMore)`            | Next page of that shelf (append, infinite scroll)                                                                                                                                                                                                                                                 |
| `libraryFilesLoaded(view, items, hasMore, total)`          | First page of one Library-section view (replace); `view` is `saved`/`all`, `total` its file count, -1 when the page failed (ADR 0007, issue #222)                                                                                                                                                 |
| `libraryFilesMore(view, items, hasMore, total)`            | Next page of that view (append, infinite scroll); `total` is -1 (an append changes no count)                                                                                                                                                                                                      |
| `homeLoaded(source, sections)`                             | One My Music source's Home landing (Browse-shaped shelves, account-scoped; each section names its source)                                                                                                                                                                                         |
| `playlistCategoryResolved(apiPath, title, count, firstId)` | A Browse playlist category's members are known, so DOWNLOAD ALL can confirm with a count                                                                                                                                                                                                          |
| `playlistFolderLoaded(source, folderId, rows, path)`       | One source's My Music playlist folder contents arrive (issue #11); empty rows and path on failure                                                                                                                                                                                                 |

My Music renders **one source group per provider whose live session can fill
shelves** (issue #259). `myMusicSources()` answers that list — each source's
descriptor identity, the label its group shows only when a second source
contributes, and the shelf categories its capabilities declare — and
`myMusicEmpty()` answers the pane's one empty state (the provider that could
fill it, its own sign-in or setup verb, and the sentences naming it) while no
source can. Every page loads through the source's OWN provider
(`favorites_page` for the favourites shelves, `user_collections`/`folder_tree`
for playlists and mixes), and every favourites/playlist/mix row is built by
that provider's `row_for` -- folder navigation rows keep the bridge's own
folder vocabulary. A provider that later declares FAVORITES appears with no
QML edit.

Above the source groups sits the **Library section** (ADR 0007, issue #222):
provider-independent, it lists the files the scan found on disk.
`myMusicLibrary()` answers its shape (`configured` plus the two view ids, Saved
first), and `loadLibraryFiles(view)` / `loadMoreLibraryFiles(view, offset)`
page the scan's own file rows — Saved is the files carrying an on-disk Waves
item id, All files every audio file the walk sees. The rows and counts never
cross to a provider; the only descriptor-made field is each tagged row's
`provider`/`provider_logo` badge, derived from the item id's namespace (a bare
id reads as TIDAL's, `waves.ids`) and the registered provider's own mark, so
an untagged row carries neither and no row ever guesses one. Because the rows
are the same file facts the scan publishes, the section's counts and the
search badges cannot disagree.

## Browse (editorial pages)

| Signal                          | Fires when                                                                                                              |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `browseLoaded(payload)`         | The Browse landing page (sections + genre/mood/decade chips)                                                            |
| `browsePageLoaded(payload)`     | One drilled-into page, keyed by its TIDAL api path                                                                      |
| `browseSectionMore(payload)`    | A section's "load more" page                                                                                            |
| `browseTileArt(apiPath, urls)`  | Cover mosaic for one genre/mood/decade tile, streamed progressively                                                     |
| `browsePagePrefetched(payload)` | A hover-armed prefetch finished building a page; carries that page's art summary so the card can paint its hero at once |

`prefetchBrowseItem(kind, mediaId)` is the hover half of the same family: a
dwell on a card (or on a track row, for the album behind it) builds the page
on a worker before any click, so the open that follows is served from the page
cache. Exactly one prefetch is in flight at a time, it is dropped on a logout
generation bump, and the click that catches up to it claims the result rather
than rebuilding. It shares `_build_browse_item` with a real open, so it is not
side-effect free: that builder ends by recording the page's member track ids
(`record_members_replace`) and emitting `collectionMembershipChanged`, which
the hovered card answers by re-querying its ownership rollup. A hover
therefore costs what an open costs on that path.

`prefetchAlbumTracks(albumId)` is the album-row half: a dwell on a row fetches
that album's tracks so the expand which usually follows opens on them instead
of "Loading tracks…". Unlike its browse sibling it is silent, emitting nothing
and recording no membership (the expand does that, see `loadAlbumTracks`), and
a cached or already-in-flight album is a no-op. One unwatched fetch at a time:
a second hover while one is running is DROPPED, never queued, because the same
pool serves real clicks.

`prefetchArtist(artistId)` is the artist-card half: a dwell on an artist card
(search results, browse shelves, the library's Artists grid) builds the artist
page so the click that follows paints it from `_artist_cache` instead of
"Loading artist…". Silent like the album-row half (nothing emitted, no busy,
no status), one in flight at a time with a second hover dropped, and a page
already cached under the current edition rule is a no-op (the click paints it
at once and revalidates). A click on the hovered card mid-flight claims the
build (`loadArtist`), which then lands as that click's, status and busy
included. It shares `_start_artist_build` with the click.

## Download queue

| Signal                                                                       | Fires when                                                                                                                                 |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `queueChanged(rows)`                                                         | Full resync: the whole queue as dicts (initial state, wholesale rebuilds, and any change touching most rows at once)                       |
| `queueRowsAdded(rows)` / `queueRowsChanged(rows)` / `queueRowsRemoved(qids)` | The delta protocol: most mutations cross as just the rows concerned (complete row dicts; removals as qids), coalesced per GUI-thread flush |
| `queueItemProgress(qid, pct)`                                                | A queued item's aggregate progress ticks                                                                                                   |
| `queueTracksLoaded(qid, tracks)`                                             | Full per-track snapshot for an expanded queue row                                                                                          |
| `queueTrackState(qid, row)`                                                  | One track's lifecycle change inside a job                                                                                                  |
| `queueTrackPct(qid, map)`                                                    | Batched live percentages for downloading tracks                                                                                            |
| `pausedChanged`                                                              | Global pause/resume toggled                                                                                                                |
| `folderRemaining(folderId, remaining, total)`                                | A playlist-folder job's member count ticks as members complete or fail; drives its badge                                                   |
| `scanningChanged`                                                            | A discography, videos, editions or playlist scan starts or ends (property `scanning`); keeps STOP visible                                  |
| `downloadProgress(mediaId, pct)` / `downloadState(mediaId, state)`           | Per-media progress/state, drives the buttons and card controls outside the queue                                                           |
| `ownershipChanged(trackId)`                                                  | A track's ownership or delivered quality changed; QML re-queries `ownershipOf`                                                             |
| `ownershipChangedBatch(ids)`                                                 | First ownership answers, collected for a moment and announced once; `ids` is `,id,id,`-delimited so QML can `indexOf("," + id + ",")`      |
| `collectionMembershipChanged(id)`                                            | A collection learned its member track ids; its cards re-ask `collectionOwnership`/`collectionOwnershipDetail` in place                     |
| `downloadFolderMissing` / `downloadFolderDefault`                            | The download folder is invalid (blocking) / still the historical default (nudge)                                                           |
| `downloadFolderUnreachable(path)`                                            | The folder is an unreachable network share; queued work held for "Try again"                                                               |
| `downloadFolderRecovered`                                                    | The unreachable share came back (own remount or "Try again"); held work replays                                                            |
| `ffmpegMissingBlocked`                                                       | A download would come out degraded without FFmpeg; a blocking choice is shown                                                              |

STOP partitions the queue rather than emptying it (issue #27): every row it
ends keeps its place in a Stopped section, so alongside the Failed section's
controls the queue exposes `clearStopped()` and `retryAllStopped()`, the same
shape as their Failed counterparts. `downloadPlaylistAlbums(playlistId)`
(issue #4) resolves the source album of every track on a playlist, dedupes
them, and enqueues the set under one `albums:` rollup id.

Apple downloads (cookies tier) speak the same queue protocol: one row per
album/playlist/track, per-track `queueTrackState` events with delivered
quality words, and ownership recorded from the same done events. The bytes
arrive file-level (gamdl fetch plus local decrypt, verified by codec probe)
instead of through the TIDAL segment engine, and a missing cookies export
fails the click with a status message before anything queues. A session
rejected at a download boundary holds its row in place and pauses the run
(the light says Needs attention); the job retries once the wrapper guest
refreshes its tokens or the cookies export changes, and STOP lands promptly.
A wrapper runtime that will not start holds once, then fails the row with the
setup words and deep-links `appleSetupRequested("setup")`, so a broken tier
cannot hold forever. A row whose integrity failure quarantined a copy carries
the count and the failed row's OPEN/DELETE actions (`openQuarantine` /
`deleteQuarantine`); deleting the bytes leaves the skip-list mark, so
REDOWNLOAD stays the way back. Disabling Apple in Settings stops its queued
and running rows through the same Stopped shape STOP uses, each carrying the
reason that says why.

The per-click Chooser's two answer-only slots are capability-driven (issue
#235), so a provider is never named by QML: `chooserSupported(mediaId, kind)`
says whether a control carries the split button at all (the covered kinds plus
the row's provider metadata: a quality rung, an audio type, or a lyrics/art
capability), and `chooserDefaults(mediaId, kind)` returns the popover's data --
`provider`, `providers` (segment tiles: id, name, logo,
logo_width, selected, one per enabled provider with the row's own always
present), `tier`, `audioType` (clamped to `audioOptions`), `audioOptions`,
`atmosOnly`, `tiers`, `showLyrics`/`showLyricsTtml`/`showArt` and the
lyrics/art quick-toggles. A provider whose metadata offers nothing per-click
answers `chooserSupported` False, so no chevron renders.
`artistDownloadSupported(artistId)` is the same kind of answer for the artist
page's discography control (issue #288): True only where the artist's provider
declares `Capability.ARTIST_DOWNLOAD`, so an Apple artist page renders no
control for the verb its catalog cannot answer (the click is refused with
honest words either way).

## Local library presence (the "in your library" badge)

The scan family lives in `bridge_library.py` (`LibraryMixin`, mixed into
`WavesBridge`); `waves/library_index.py` walks the configured folder and
`waves/matching.py` decides what counts as the same album. The walk runs in a
child process (`waves/library_worker.py`, driven by
`waves/waves_ui/library_proc.py`'s `LibraryWorker`), so a long scan never holds
the interpreter lock the interface thread needs.

Ownership (the record of what Waves itself downloaded) is scoped to at most two
roots, the download folder and the library folder (`_ownership_roots`): a
recorded path outside both never counts and is never statted. `ownershipOf`
answers carry `in_library` and `folder` per copy, and
`collectionOwnershipDetail(ids)` rolls them up for an album or playlist, so a
finished button reads IN LIBRARY or DOWNLOADED by where the copy lives and its
click can name that folder.

`decide_presence` answers at two strengths and the difference matters. `present`
lights the pill and is generous. Beyond it the verdict splits into two
independent axes: `sure` is IDENTITY (a year on both sides agreeing within one,
and the title matching with its edition qualifiers intact), rendered as the
badge's "?" (dropped when proven) and the choice between a green in-library
button and the gold MAYBE; `full` is COVERAGE (a known source track count the
local copy meets), rendered as N OF M and the cyan PARTIALLY button. `full`
alone picks the button's shape (a complete copy replaces Download, however
hedged its words; a short one keeps a live button), and every claim stays
clickable and opens the gate, so a wrong match never dead-ends. `partial` False
remains the strict both-axes bar for the consumers where being wrong costs a
download outright: the bulk skip claims. The download engine never sees any of
it (pinned by `test_presence_never_reaches_the_download_engine`).

| Signal                     | Fires when                                                                         |
| -------------------------- | ---------------------------------------------------------------------------------- |
| `libraryPresenceChanged`   | The presence index (re)built or was cleared; QML re-queries `libraryAlbumPresence` |
| `libraryScanStatusChanged` | The scan's status or live progress moved; Settings re-reads `libraryScanStatus()`  |
| `librarySourceChanged`     | A library pref committed (switch, source or folder); the Settings card re-reads    |

Synchronous slots (answered from the in-memory index, no disk I/O):
`libraryAlbumPresence(artist, title, year, tracks[, duration])` (duration is
TIDAL's total seconds, the play-length identity witness),
`libraryTrackPresence(artist, title[, album, album_year[, duration]])` (the
exact-song answer behind a track's pill and its download button's claim face;
the album pair and the track's seconds are what the identity can be proven
against, and callers that omit them get `sure` False),
`artistLibraryPresence(name)`, `libraryScanStatus()`, `libraryScanProgress()`,
`librarySource()`, `libraryDownloadFolder()`,
`rescanLibrary()` (forces a full re-list) and `revealLibraryAlbum(path)`
(opens the matched folder in the file manager, resolved on a worker).

With the opt-in `library_mb_arbiter` pref on (off by default: it sends artist
and album-title search terms to musicbrainz.org), `libraryAlbumPresence` may
also overlay a MusicBrainz verdict onto an unproven answer: the lookup runs on
a worker behind a 1 req/s gate, the badge shows the unproven verdict
immediately, and `libraryPresenceChanged` re-announces when a proof lands. The
overlay can only ever upgrade `sure`; the bulk claim gate never reads it.

The whole family is gated on the `library_enabled` pref, off by default: while
it is off `_library_root()` resolves nothing and no folder is ever scanned. The
Settings card stages `library_enabled` / `library_bulk_skip` /
`library_source` / `library_folder` into the page's edit map, and SAVE CHANGES
commits them through `applySettings`, which also starts the first scan of an
enabled, configured library. `rescanLibrary()` acts only on the saved
configuration.

Bulk claim gate (`library_bulk_skip`, on by default, inert while the master
switch is off): bulk downloads leave out what the scan claims. A discography
drops fully claimed albums and guest tracks before queueing
(`_library_claims_album` / `_library_claims_track`), and a playlist's
`downloadPlaylistAlbums` (issue #4) runs the identical album-grained gate over
the albums its tracks came from; a collection job gets a
`library_claim` callable injected into the engine, consulted per track only
after the exact-id ownership gate declines and never for a merge-plan member
(`_claim_verdict`). Single-item jobs never get the callable, and
`downloadAlbumAnyway(album_id)` (the claim dialog's DOWNLOAD ANYWAY) registers
a per-album override so that click really downloads.

Both claims are strict on IDENTITY, not just presence. The track claim asks
whether a copy is already filed under the release being fetched, so the album
has to reach it: an album job passes its own release (the only place the year
is reliably spelled out), a playlist or mix lets each track name its own, and
a track with no release to name is fetched. Reading bare presence as a claim
was issue #24: a title and artist match every compilation and re-release that
share them, so tracks were dropped out of albums the user had explicitly
asked for.

## Preview and video playback

| Signal                          | Fires when                                                         |
| ------------------------------- | ------------------------------------------------------------------ |
| `previewState(kind, id, state)` | Resolve lifecycle for a preview, addressed by (kind, id)           |
| `previewReady(kind, id, url)`   | A streamable URL for QML's shared MediaPlayer                      |
| `previewMeta(...)`              | Now-playing metadata (title, artist(s), art, ids for navigation)   |
| `videoReady(payload)`           | A video stream URL resolved for the overlay player                 |
| `videoPeekReady(payload)`       | A hover-peek stream for a video card resolved (or carries `error`) |

The preview state model: exactly one preview plays at a time. `kind` is
what the user clicked ("track", "artist", "album", "playlist", "mix");
non-track kinds resolve to a concrete song, reported via `previewMeta`'s
`trackId`, which is how every surface showing that song displays live
state instead of offering a restart (see `pvActive` in Main.qml).
TIDAL previews stream the full track; Apple previews play Apple's
documented 30-second clip URL directly (no remux).

## FFmpeg manager and self-updater

| Signal                                                                                                              | Fires when                                                      |
| ------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `ffmpegStatusChanged` / `ffmpegProgress(pct)` / `ffmpegStateChanged(state, msg)` / `ffmpegUpdateChecked(...)`       | The managed-FFmpeg install/update lifecycle (ffmpeg_manager.py) |
| `appUpdateStatusChanged` / `appUpdateProgress(pct)` / `appUpdateStateChanged(state, msg)` / `appUpdateChecked(...)` | The self-updater lifecycle (updater.py)                         |

## Internal signals (thread hops)

Signals prefixed `_` are not for QML; they marshal work back onto the GUI
thread: `_albumsQueued` (batch-enqueue a resolved discography),
`_tracksQueued` (same batch marshalling for individual tracks),
`_mediaRefetched` (re-dispatch a download whose object was evicted from the
cache), `_queueTracksFetched` (merge a track snapshot without racing live
events), `_folderTreeWarmed(source)` (one source's folder sweep finished;
the parked drill-ins for that source replay).

The My Music slots name their source, so the doc's payload rule applies to
them too: `loadLibrary(source, category[, quiet])`,
`loadMoreLibrary(source, category)`, `setLibrarySort(source, category, order,
direction)`, `loadHome(source[, haveCached])` and
`openPlaylistFolder(source, folderId)`; `myMusicSources()` /
`myMusicEmpty()` are the pane's answer-only data (see Search, artist pages,
library above). The Library section's slots are the one provider-free pair:
`loadLibraryFiles(view)`, `loadMoreLibraryFiles(view, offset)`, with
`myMusicLibrary()` as their answer-only shape.

## Adding a new signal

1. Declare it with the others in backend.py, with a comment saying what it
   carries and when it fires (payloads are plain dicts/lists/strings only;
   tidalapi objects never cross the bridge).
2. Emit it from the worker; do not touch bridge state from the worker.
3. Handle it in Main.qml's `Connections { target: waves }` block
   (`function onYourSignal(args) { ... }`).
4. Add a row here.

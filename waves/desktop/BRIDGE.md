# The QML/Python bridge

`WavesBridge` (backend.py) is exposed to QML as the context property
`waves`. QML calls its `@Slot`-decorated methods; the bridge answers by
emitting signals, which Main.qml consumes in one big
`Connections { target: waves }` block. Because slots run their blocking work
on thread pools and emit from worker threads, Qt delivers every signal on
the GUI thread (queued connection); QML handlers never see a race.

The signal declarations in backend.py carry inline comments with the exact
payload shapes. This file maps signals to features; [the architecture map](../../docs/architecture.md)
links their Python, QML and test owners. Settings payload construction belongs
to `settings/schema.py`, provider cards/status to `providers/presentation.py`.
Their Qt entry points remain on this context object.

## Download policy settings

`settingsSchema()` exposes the one `settings.json` policy store through dotted
`download_policies.*` field keys. `applySettings(values)` validates and commits
these alongside existing preferences. Opening Settings and Cancel do not write.
Shared rules live under Downloads, sparse overrides and engine/operation orders
under the owning provider, and bounded retry/timeouts plus provider pacing under
Advanced. Diagnostics retains explicit probes and redacted capture.

Existing quality tier strings, per-provider lyrics/art mirrors, shared video
values and pacing values keep their original persistence keys. The additive
policy store requires no replay of a migration or reset; settings writes and
migration completion retain their existing atomicity and downgrade guards.
Cross-provider choice, failure recovery, upgrades and enrichment are independent
and default off. Policies capture intent for the corresponding execution owners;
new fulfillment capabilities remain subject to their implementation and gates.

## Application events

| Signal                                                | Fires when                                                                            |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `applicationEvent(payload)`                           | A guarded event is delivered or its lifecycle changes; payload is redacted plain data |
| `applicationEventActionRequested(action, providerId)` | An applicable Settings or logs action asks Main to navigate                           |
| `notificationsChanged()`                              | The retained notification history or its active count changed                         |

`applicationEvent(payload)` delivers redacted plain data on the GUI thread:
`id`, `code`, `severity`, `domain`, `scope`, `title`, `summary`, `details`,
`diagnostics`, `references`, `retryable`, `lifecycle`, `actions`, `occurrences`.
References are `{provider_id, engine_id, runtime_id, job_id, media_id}`; absent
job identity is `null`, other absent references are empty strings. Normal
presentation uses title/summary; redacted exception traces belong only in the
optional diagnostics detail. No exception objects cross this signal.

Identity is an opaque lifecycle/dedup key. A repeated active issue updates that
identity and increments `occurrences`. Recovery and dismissal publish terminal
updates with no actions. Operations sharing a legacy signal retain distinct
event identities; a successful setup probe does not resolve an install failure.
Provider/job/generation guards reject stale results and
are checked again before dispatch. The bridge retains active action context.

`eventAction(id, action)` returns whether an advertised, applicable action ran.
Allowed commands are `open_settings`, `open_logs`, `reconnect`, `retry_job`,
`copy_diagnostics`. Reconnect and retry re-enter the existing provider/job
flows; copy re-scrubs the event. Settings/log navigation emits
`applicationEventActionRequested(action, providerId)` for Main to handle.
`dismissEvent(id)` removes active actions and publishes `dismissed`; a retained
issue restored by a restart, which has no live action context, is dismissed in
the stored history instead.

## Notification center

The notification center is the structured events' product consumer. Main.qml's
`NotificationToasts` shows at most three notices (four-second success/info,
eight-second warning, sticky errors), merges nearby download completions per
provider into one aggregate, pauses dismissal while the pointer or keyboard
focus rests on a notice, and routes anything over the limit plus every resolved
notice to `NotificationCenter` (a right-edge drawer). The bridge owns the retained
history: one redacted entry per event identity beside the Waves prefs
(`notifications.json`), capped by `notify_history_max` / `notify_history_days`
(defaults 200 / 7 days; active issues stay until resolved or dismissed).
Resolution flows through the relay, so an owner can close a retained entry
after a restart even when the live action index no longer holds it.

| Slot                         | Contract                                                                                     |
| ---------------------------- | -------------------------------------------------------------------------------------------- |
| `notificationHistory()`      | Every retained entry, newest update first (the center's list)                                |
| `notificationStatus()`       | `{active, count}` for the header badge; re-read on `notificationsChanged`                    |
| `clearNotificationHistory()` | Drops resolved/dismissed history; active issues stay discoverable                            |
| `copyEventDiagnostics(id)`   | Copies one entry's redacted text; works for terminal history too                             |
| `reportEventIssue(id)`       | Opens a reviewable prefilled new-issue draft for the project repository; the user submits it |

Toast preferences (Settings > Notifications): `notify_completion_toasts` (off
keeps completions in the center only), `notification_motion` (off disables the
slide/fade), `notify_history_max` (0-200), `notify_history_days` (1-30).

Legacy status/error text, install/update state messages, queue failure reasons
and log display/copy are redacted before their consumers receive them. Existing
log, diagnostics-export and update actions remain available.

## Session and status

| Signal                                                                                             | Fires when                                                                                                       |
| -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `loggedInChanged`                                                                                  | Login/logout completes (property `loggedIn`)                                                                     |
| `sessionResolvedChanged`                                                                           | The restored session finishes resolving (property `sessionResolved`)                                             |
| `statusChanged`                                                                                    | The status-bar text changes                                                                                      |
| `busyChanged`                                                                                      | A blocking operation starts/ends                                                                                 |
| `loginUrlReady(url)`                                                                               | The browser-login URL is ready to open                                                                           |
| `backRequested`                                                                                    | The platform back gesture (macOS trackpad swipe) asks to navigate back                                           |
| `motionBgChanged`                                                                                  | The motion-background preference flipped; Main.qml re-reads it                                                   |
| `confirmCategoryDlChanged`                                                                         | The "confirm DOWNLOAD ALL on a Browse category" preference flipped (property `confirmCategoryDl`)                |
| `skipExistingChanged`                                                                              | The "Skip existing" download setting flipped (property `skipExistingFiles`); the claim gate re-reads its copy    |
| `settingsPersistedExternally`                                                                      | Settings were saved by something other than the Settings page (a dialog, a recovery); the page re-reads          |
| `forwardRequested`                                                                                 | The mouse forward button asks to navigate forward (the back button fires `backRequested`)                        |
| `hoverMotionChanged` / `artHoverTiltChanged` / `videoHoverPeekChanged`                             | The matching motion preference flipped (`setWavesPref`); the surfaces re-read it                                 |
| `notificationMotionChanged`                                                                        | The notification motion preference flipped; the toast stack re-reads it                                          |
| `diagnosticsExported(path)`                                                                        | A diagnostics export finished (`""` = failed)                                                                    |
| `appleStatusChanged`                                                                               | A save moved `apple_enabled` or the session; Settings re-reads `appleStatus()`; search clears when off           |
| `appleWrapperAuthChanged`                                                                          | The wrapper guest auth snapshot moved (login, logout, 2FA, probe); the wizard form re-reads `appleWrapperAuth()` |
| `appleSetupRequested(reason)`                                                                      | Apple needs setup (`setup` on enable, `cookies` on a pre-setup download click); Main deep-links to the wizard    |
| `setupRequested()`                                                                                 | Settings -> Providers -> "Set up providers" asks to re-open the provider welcome surface as a page               |
| `signInRequested(providerId)`                                                                      | A provider card asked for sign-in; the welcome surface opens that provider's steps (or its cards)                |
| `providerStateChanged(providerId)`                                                                 | An account/readiness change invalidates only the named provider's retained presentation state                    |
| `providerLoginUrlReady(providerId, url)`                                                           | The current selected provider login attempt has a browser URL ready                                              |
| `providerLoginFinished(providerId, ok)`                                                            | The current provider login attempt settles successfully or fails; cancelled/stale attempts never fire            |
| `appleRuntimeStatusChanged` / `appleRuntimeProgress(pct)` / `appleRuntimeStateChanged(state, msg)` | Apple install/pull, start, setup and sign-out state; re-read `appleSetupState()`                                 |

The provider cards' action pills dispatch through one slot, not per-provider
handlers: `providerAction(providerId, actionKey)` runs the key the schema
carried (`<provider id>_<verb>`). The generic verbs run through the provider
seam (`signin` starts the provider's login flow; `signout` runs its sign-out
or the app-level flow registered for it), and bridge-owned verbs (Apple's
runtime management) come from the registry built where the providers are
wired. `appleStatus()` answers `{state, word, actions}` — the same action
list the schema bakes — so a live light flip moves its pills with it.

`providerReadiness(providerId)` answers `{enabled, account, catalog,
operations}`. `enabled` is true/false/unknown (`null`); `account` is
`signed_in`, `signed_out` or `unknown`. `catalog` and each operation's
`state` are `ready`, `disabled`, `sign_in_required`, `setup_required`,
`unknown` or `unsupported`; operation entries are `{state, action}` keyed
by capability. Actions are `signin`, `setup` or empty. Static capability
declarations never imply live readiness, and catalog access does not require
an account where a provider offers public access.

`providerStateChanged(providerId)` refreshes these live presentations and
invalidates only that provider's Search source, saved shelves, retained media
maps and history. Identity is resolved through `providerDescriptor`, including
bare legacy TIDAL IDs; unrelated providers retain their rows and pages.

Browser auth uses `beginProviderLogin(providerId)`,
`completeProviderLogin(providerId, payload)` and
`cancelProviderLogin(providerId)`. `providerLoginUrlReady(providerId, url)`
opens the browser only while that provider's selected steps are active.
`providerLoginFinished(providerId, ok)` completes the selected successful
flow. Cancel/Escape invalidates the attempt and cancels pending paste decode;
stale worker results cannot publish or commit credentials. Legacy
`beginLogin`, `completeLogin` and `loginUrlReady` remain compatibility APIs;
shared QML uses the provider-scoped APIs.

The header's per-provider marks come from two answer-only slots, both
composed from the descriptors so a third provider needs no QML edit
`providerLights()` answers `[{id, name, state, word}]`, one
entry per provider with a status to report: a session-kind provider's
sign-in state (`signed_in` / `signed_out`, worded with the card's own
"Signed in" / "Signed out") or a setup-kind provider's setup light (Apple's
five states, `off` contributing none). The QML renders a dot per entry — the
colour is the shared status-light vocabulary in `qml/StatusLight.js` — and
re-reads on `providerStateChanged` and legacy `loggedInChanged` / `appleStatusChanged`; sign-out lives on the
provider card, never in the header. `browseNav()` answers `{available,
signed_in, provider, message, action, action_label}`: Browse exists while a configured provider declares
`Capability.BROWSE` and is hidden when none does (never a permanently blank
tab). `signed_in` reports whether ANY browse-capable provider is ready (the
combined landing loads that provider's sections even while another needs an
account); `provider`/`message`/`action` still name the first capable
provider for the none-ready call to action, and the landing dispatches that
action through `providerAction`.

`providerSignInSteps()` answers registered browser-flow provider IDs. All
use the shared browser/paste component with the selected provider's ID and
name. `signInRequested(providerId)` selects those steps without opening a
browser; its explicit button starts the flow. Setup flows dispatch through
`providerAction(providerId, "setup")`, retaining the provider's own wizard.

The welcome surface's cards come from `providerCards()`: one entry per
registered provider with its descriptor identity (id/name/logo), its
`summary` (the one-line capability truth) and `action` (the provider's own
action words — a setup for Apple, a sign-in for TIDAL), plus `state`/`word`
from the same light composer as the header's marks ("" when the provider has
nothing to report, e.g. Apple switched off), plus `readiness` and
`login_flow` (`browser` by default, `setup` for Apple's wizard), and `engines`
(the same list as `providerEngines(providerId)`). The surface re-reads the list
at boot, when the surface opens and on the same flips as the lights, so a
card never states a stale account state.

`providerEngines(providerId)` returns safe subordinate execution detail, or `[]`
for a provider without engines. Each entry carries `id`, `name`, `client`,
`compatible_versions`, `recommended_operations` and `requirements`. A requirement
names `operation`, `codecs`, `audio_types`, `tiers`, `runtime`, `runtime_kind`,
`account_boundary`, `protocol`, `formats`, `state` and `action`. These are capability/setup
facts, not verified item availability or qualification claims. No paths, runtime
endpoints, credentials or personal account identifiers enter this payload.
The slot reads cached facts and schedules a coalesced worker refresh; cold or
unverified facts remain unknown. Prepared facts return through the internal
`_catalogEvent` relay and a guarded GUI receiver; provider revocation and setup
changes discard pending results. Re-read on provider/session/setup changes and
`appleStatusChanged` after refresh. Missing optional requirements affect only
operations that use them.

`appleSetupRequested(reason)` carries the wizard step a pre-setup click was
missing: `"cookies"` (no account yet — the cookies/wrapper tier) or
`"runtime"` (no fetch binary), or `"setup"` / `""` for the wizard's top. The
Apple wizard marks the named step in place, and SKIP FOR NOW leaves the page
for Search with Apple still enabled.

## Search, artist pages, library

| Signal                                                     | Fires when                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `searchResults(payload)`                                   | Search or a pasted TIDAL/Apple Music link makes progress; one emission lands per provider as it answers. `payload.sources` names every enabled search provider in registry order with its own state (`loading`/`ready`/`failed`) and safe failure words, which the page shows with a RETRY and a compact source mark. `payload.sections` folds the arrived provider groups into kind-keyed rows, each row labelled with its `sources: [{provider, id}]`; a high-confidence equivalent returned by several providers is one row exposing them all, and an uncertain row keeps its single source. `payload.top` is the first provider's pinned best match or None. A payload without `refresh` paints a fresh page (navigation, scroll reset, build veil); `refresh: true` reconciles the page already on screen in place |
| `albumTracksLoaded(albumId, tracks)`                       | An album's ordered track list arrives (album expansion)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `artistLoaded(payload)`                                    | An artist page (bio, discography, top tracks) is ready                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `artistMetaLoaded(artistId, popularity)`                   | Late-arriving artist metadata                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `playlistTracksLoaded(playlistId, tracks)`                 | A playlist's ordered track list arrives (playlist expansion); empty on failure                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `artistLoadFailed(artistId)`                               | An artist page could not load and nothing is cached; clears the Back-restore latch so history recording continues                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `libraryLoaded(source, category, items, hasMore)`          | First page of one My Music source's shelf category (replace); `source` is a provider id                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `libraryMore(source, category, items, hasMore)`            | Next page of that shelf (append, infinite scroll)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `libraryFilesLoaded(view, items, hasMore, total)`          | First page of one Library-section view (replace); `view` is `saved`/`all`, `total` its file count, -1 when the page failed (ADR 0007)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `libraryFilesMore(view, items, hasMore, total)`            | Next page of that view (append, infinite scroll); `total` is -1 (an append changes no count)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `homeLoaded(source, sections)`                             | One My Music source's Home landing (Browse-shaped shelves, account-scoped; each section names its source)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `playlistCategoryResolved(apiPath, title, count, firstId)` | A Browse playlist category's members are known, so DOWNLOAD ALL can confirm with a count                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `favoriteTracksResolved(source, count)`                    | A shelf's favourite-track count is known (-1 when the count failed); the shelf's pending flag turns it into the shared bulk confirm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `favoriteAlbumsResolved(source, count)`                    | A shelf's favourite-album count is known (-1 when the count failed); the shelf's pending flag turns it into the shared bulk confirm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `favoriteArtistsResolved(source, count)`                   | A shelf's favourite-artist count is known (-1 when the count failed); the shelf's pending flag turns it into the shared bulk confirm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `favoritePlaylistsResolved(source, count)`                 | A shelf's playlist count (folders at any depth included) is known (-1 when the count failed); the shelf's pending flag turns it into the shared bulk confirm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `favoriteMixesResolved(source, count)`                     | A shelf's mix count is known (-1 when the count failed); the shelf's pending flag turns it into the shared bulk confirm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `favoriteVideosResolved(source, count)`                    | A shelf's favourite-video count is known (-1 when the count failed); the shelf's pending flag turns it into the shared bulk confirm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `playlistFolderLoaded(source, folderId, rows, path)`       | One source's My Music playlist folder contents arrive; empty rows and path on failure                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |

My Music renders **one source group per provider whose live session can fill
shelves**. `myMusicSources()` answers that list — each source's
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

Above the source groups sits the **Library section** (ADR 0007):
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

The landing is combined from every READY browse-capable provider's own
recipe (`Provider.browse_landing()`), in registry order. Each section and
chip link carries `provider_id` (its owner), the payload carries
`sources: [{provider, name}]` of the composing providers, and every
drill-down routes back through that owner: `openBrowsePage(apiPath, title,
providerId)`, `openBrowsePlaylists(apiPath, title, providerId)` and
`loadBrowseSectionMore(key, dataPath, offset, modType, title, providerId)`
each require `Capability.BROWSE` and READY readiness for the id (an unknown,
disabled or signed-out provider makes no request and emits nothing). A
provider whose recipe or page reads fail loses only its own rows; the
payload is an error only when every attempted provider failed. Editorial
page caches are keyed `browse:<provider>:<path>` / `pl:<provider>:<path>`; a
legacy bare path — an upgraded nav snapshot or disk cache — still reads as
TIDAL's.

| Signal                          | Fires when                                                                                                              |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `browseLoaded(payload)`         | The combined landing page (sections + per-provider genre/mood/decade chips + sources)                                   |
| `browsePageLoaded(payload)`     | One drilled-into page, keyed by its path and stamped with its owning provider                                           |
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

Parked pages revalidate in place: `refreshArtist(artistId)` and
`refreshBrowseItem(kind, mediaId)` are the max-age timers' silent slots for a
page the UI is still showing (entry slots revalidate only on entry, and Back
restores from memory). Nothing is re-emitted unless the rebuilt page differs
(an artist page carries `refresh: true`), busy and the status line are never
touched, a page fetched within the minute or already building is left alone,
and a page with no cache is not their load to make.

While a page is the view, a five-minute ceiling timer re-pokes its silent
slot (`browseLandingFreshTimer` → `refreshBrowse`,
`browseItemFreshTimer` → `refreshBrowseItem`,
`artistFreshTimer` → `refreshArtist`,
`libraryFreshTimer` → a quiet `loadLib` of the visible pane), so a parked
page tracks TIDAL instead of freezing at its open. The timers stop while the
window is hidden or minimized (`windowUp`); a re-show after at least one
interval down fires each running timer once, and the bridge slows its share
keep-warm while hidden (`windowShown(up)`, every tenth tick) so a NAS gets
an idle stretch. Every refresh is throttled backend-side and repaints only
on a change, with the scroll spot held.

Cards and rows arrive dressed: a browse card carries its library verdict
(`lib`) and the publish that answered it (`libStamp`, compared before the
card trusts the answer), plus its ownership rollup (`own`/`ownGen`, except a
`pending` rollup, which is left to ask live). A shelf category row (albums,
tracks, artists) carries the same `lib`/`libStamp` pair keyed by category,
and an expanded album/playlist panel's track rows likewise. The caches behind
them stay undressed (a persisted verdict would be stale on the next launch),
and a cross-account emit is dropped by generation.

Catalog workers capture the provider epoch before dispatch and check it again
when their results reach the GUI. Sign-out or disable prunes that owner's
memory and disk entries while unrelated providers retain theirs. Disk page
and search snapshots use version 8 with opaque per-provider account stamps;
legacy mixed-account snapshots are discarded and rebuilt.

## Download queue

| Signal                                                                       | Fires when                                                                                                                                 |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `queueChanged(rows)`                                                         | Full resync: the whole queue as dicts (initial state, wholesale rebuilds, and any change touching most rows at once)                       |
| `catalogOffersLoaded(requestId, offers)`                                     | Chooser metadata work finishes: request ID and neutral offer dicts after queued context validation; cancelled requests never fire          |
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
| `qualityOverridesChanged`                                                    | A per-item quality choice was set or cleared; QML re-reads `qualityOverrides`                                                              |
| `qualityChoiceChanged(scope)`                                                | The media ids whose download standing a choice moves (the item, every track for an album); buttons re-ask ownership                        |
| `targetTierChanged`                                                          | The Settings quality tier moved; the DEFAULT mark in every badge's quality menu follows it                                                 |
| `collectionMembershipChanged(id)`                                            | A collection learned its member track ids; its cards re-ask `collectionOwnership`/`collectionOwnershipDetail` in place                     |
| `downloadFolderMissing` / `downloadFolderDefault`                            | The download folder is invalid (blocking) / still the historical default (nudge)                                                           |
| `downloadFolderUnreachable(path)`                                            | The folder is an unreachable network share; queued work held for "Try again"                                                               |
| `downloadFolderRecovered`                                                    | The unreachable share came back (own remount or "Try again"); held work replays                                                            |
| `ffmpegMissingBlocked`                                                       | A download would come out degraded without FFmpeg; a blocking choice is shown                                                              |

STOP partitions the queue rather than emptying it: every row it
ends keeps its place in a Stopped section, so alongside the Failed section's
controls the queue exposes `clearStopped()` and `retryAllStopped()`, the same
shape as their Failed counterparts. `downloadPlaylistAlbums(playlistId)`
resolves the source album of every track on a playlist, dedupes
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

Queue rows carry `askEngine` (`auto`, an engine ID, or empty for a provider
without engine selection) and `enginePreferences`, captured when queued.
Retry preserves both and the private immutable request intent: origin identity,
shared/provider rules, quality/type/codec/video requirements, lyrics/art mirrors,
metadata/organization/duplicate preferences and recovery permissions. Changes
in Settings apply to new requests. Intent carries no cookies, credentials or
network origins and never crosses the QML payload. Auto checks live readiness
within its captured orders and constraints; a selected provider still permits
Auto engine selection. Delivered quality includes `engine_id` and
`runtime_id` for the actual route. Engine choices in Settings affect new jobs.

The per-click Chooser renders provider metadata and current offer evidence.
`chooserSupported(mediaId, kind)` determines whether the split-button carries
options. `chooserDefaults(mediaId, kind)` supplies effective provider defaults:
`provider`, `tier`, `audioType`, `audioOptions`, `atmosOnly`, `tiers`, asset
capability flags and toggles, plus `engines` and the saved `engine` choice.
Shared QML branches on these facts rather than provider identity.

`requestCatalogOffers(mediaId, kind, tier, audioType[, selectedProvider, engine])`
returns a request ID and starts bounded worker identity/metadata/manifest work.
`catalogOffersLoaded(requestId, offers)` delivers neutral values after memory-only
GUI-thread context validation; `cancelCatalogOffers(requestId)` revokes publication.
Offers include origin/fulfillment IDs, confidence, readiness/action, separate
advertised/probed/selected/delivered facts, ownership/presence, timestamps,
explanations, the provider `descriptor` and its `options`. Missing facts stay
unknown; Apple advertised traits do not establish exact rendition availability.
Track Library presence comes from the scanned match index independently of
provider Ownership. An unbuilt index or unproven candidate stays unknown;
an owned download outside the Library does not establish Library presence.
An index miss stays unknown during a scan, on an unreconciled partial index,
or after a failed/unavailable scan. A complete trusted or reconciled index can
establish absence; matching entries can still establish presence independently.
Separate catalog recording and release-version qualifiers participate in the
Library match; a base Edition does not prove its Deluxe or remastered Edition.
Library folder, index-publication or scan-completeness changes invalidate the request
through memory-only guards. An open Chooser marks Library evidence stale on
`libraryPresenceChanged` or `libraryScanStatusChanged`, retains its choices, and coalesces replacement work
through a three-second quiet window. It waits for an active Library scan to
finish before restarting provider probes. Closing or an explicit offer refresh
cancels the pending Library refresh.
An engine pin is applied only to its selected provider's evidence, even when
the origin provider remains unpinned.

`chooserSwitchOptions(requestId, providerId, explicitChoices)` proposes target
`values`, retained `explicit` choices and `changes` requiring confirmation,
with `provider`, `mediaId` and `options`; stale or unresolved alternatives return
`error`. Explicit choices use the defaults' camelCase keys; `engineProvider`
scopes an engine pin. Unpinned choices follow effective target defaults. The UI
keeps its old state until incompatible changes are confirmed and revalidates the
proposal. Unresolved rows explain their missing/conflicting identity rather than
silently choosing candidates. `setupChooserProvider(providerId, action)` opens
that provider's setup/sign-in or Settings, without implicitly enabling it.

`downloadCatalogOffer(requestId, providerId, tier, audioType, toggles)` validates
the current snapshot and returns whether dispatch was admitted. Offer
readiness must be `ready`; disabled, sign-in/setup-required, unknown and
unsupported offers refuse dispatch and leave the Chooser open. Known probe
incompatibility refuses dispatch without changing the selected requirement;
unknown exact rendition evidence remains unknown. Enqueue retains
the origin ID independently of fulfillment identity, preserving legacy source
keys. Toggles contain only explicit assets, optional `engine`, `provider_pin`
(empty means unpinned), and independent `allow_provider_fallback` /
`allow_engine_fallback` consent. They relax only their own pins within saved
policy permissions, never delivery constraints. The compatibility
`downloadWithChooser` slot still accepts `allow_fallback` for both dimensions.
Changing defaults affects new requests; retry retains captured intent. Main
Download keeps the saved policy/source-default path. Automatic fulfillment and
recovery remain owned by #595; this UI does not add an automatic executor.
Preview retains its own identity and provider-specific duration.

The anchored Chooser stacks offers, expands only the selected offer, scrolls
within window bounds and restores focus on close. Set as defaults writes the
provider audio override and existing quality/assets through the staged writer;
shared defaults remain independently editable.
`artistDownloadSupported(artistId)` is the same kind of answer for the artist
page's discography control: True only where the artist's provider
declares `Capability.ARTIST_DOWNLOAD`, so an Apple artist page renders no
control for the verb its catalog cannot answer (the click is refused with
honest words either way).

`providerDescriptor(value)` is the identity answer the badges, row source
marks and the Chooser's provider chip render: `{id, name, logo,
logo_header_width, logo_header_height}` for a media id (resolved by its
namespace: a bare legacy id reads as TIDAL's) or a provider id matched
exactly (a caller asking for its own provider), and `None` for an id no
registered provider claims -- an unknown namespace wears no mark, never
another provider's. The
Library section's bulk rows carry the same fields (`provider`, `provider_logo`)
so a badge there costs no per-row crossing. QML carries no provider asset path
and never parses an id prefix to pick one.

`searchEnabled()` answers whether any registered provider's SEARCH operation
is ready. QML caches that answer and refreshes it on neutral and legacy state
signals. `searchOpportunities()` answers `[{provider, action, action_label,
message, detail}]` for providers that could fill Search after an explicit
action, including disabled setup opportunities. The empty state renders and
dispatches the list without identity branches.

`dropSearchSource(provider)` takes a provider that left the app (sign-out,
switch-off) off the displayed search page: the bridge folds its retained
provider groups again without that source, so a merged row keeps only the
sources that still exist.

`isProviderLink(text)` is a pure registered-provider allowlist and nonempty-path
check. The paste decoder uses it for automatic link submission, preserving
its one-shot paste-button arm and navigation-generation guard. Provider URL
grammar and result translation stay in Python; a host mentioned in a query,
an unrelated host or a lookalike never auto-opens.

## Local library presence (the "in your library" badge)

The scan family lives in `library/bridge.py` (`LibraryMixin`, mixed into
`WavesBridge`); `waves/library/index.py` walks the configured folder and
`waves/metadata/matching.py` decides what counts as the same album. The walk runs in a
child process (`waves/library/worker.py`, driven by
`waves/desktop/library/scan_process.py`'s `LibraryWorker`), so a long scan never holds
the interpreter lock the interface thread needs.

Ownership (the record of what Waves itself downloaded) is scoped to at most two
roots, the download folder and the library folder (`_ownership_roots`): a
recorded path outside both never counts and is never statted. `ownershipOf`
answers carry `in_library` and `folder` per copy, and
`collectionOwnership` and `collectionOwnershipMany` judge members against the
collection's quality choice (or the current default), independently of each
track's own choice. `collectionOwnershipDetail(ids, collection_id)` uses the
same context for an explicit member list; its ids-only overload retains track
choices. One ownership scan supplies the verdict and location facts, so a
finished button reads IN LIBRARY or DOWNLOADED by where the copy lives and its
click can name that folder. Existing Version selection remains in effect;
this context pins quality for the scan, not queued audio intent. Dual answers
that lack location facts cannot claim that all required Versions are in the
library.

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
`libraryAlbumPresence(artist, title, year, tracks[, duration[, explicit]])`
(duration is TIDAL's total seconds, the play-length identity witness),
`libraryTrackPresence(artist, title[, album, album_year[, duration[, explicit]]])`
(the exact-song answer behind a track's pill and its download button's claim
face; the album pair and the track's seconds are what the identity can be
proven against, and callers that omit them get `sure` False). `explicit` is
the advisory flag the bulk gates weigh (1 explicit, 0 clean, -1 unknown, the
default): a copy known to be the other edition is never `sure`. Every QML
asker and the worker's dressing pass it; an album dict's `explicit` false may
mean TIDAL said nothing, so album cards pass 1 or -1, never 0,
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
`downloadPlaylistAlbums` runs the identical album-grained gate over
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
a track with no release to name is fetched. A bare presence read
would count a title-and-artist match on any compilation or re-release that
shares them as a claim, dropping tracks out of albums the user had explicitly
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

| Signal                                                                                                              | Fires when                                                                                         |
| ------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `ffmpegStatusChanged` / `ffmpegProgress(pct)` / `ffmpegStateChanged(state, msg)` / `ffmpegUpdateChecked(...)`       | The managed-FFmpeg install/update lifecycle (`ffmpeg/manager.py`)                                  |
| `appUpdateStatusChanged` / `appUpdateProgress(pct)` / `appUpdateStateChanged(state, msg)` / `appUpdateChecked(...)` | The self-updater lifecycle (`updates/updater.py`)                                                  |
| `appUpdatePending(version)`                                                                                         | A staged update from an earlier session was re-armed at boot; Main shows the restart pill outright |

## Internal signals (thread hops)

Signals prefixed `_` are Python-only GUI thread hops. Provider tokens and
event objects stay inside Python; only the public signals carry QML payloads.

| Signal                                                                                     | Payload and delivery                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_providerLoginEvent(event)`                                                               | `LoginEvent(token, phase, url, ok, resume)`; publish committed account truth while its provider epoch is current; apply login-form effects only while its attempt is current                                                                             |
| `_catalogEvent(event)`                                                                     | `_CatalogEvent(token, deliver)`; invoke the GUI callback only while its provider context is current                                                                                                                                                      |
| `_searchEvent(event)`                                                                      | `_SearchEvent(generation, tokens, payload, status, failures)`; carries one provider group (or that provider's own failure words) per arrival; discard superseded generations, drop revoked sources and publish classified failure events before delivery |
| `_albumsQueued(token, rows)` / `_tracksQueued(token, rows)` / `_videosQueued(token, rows)` | Batch enqueue a resolved discography, guest tracks or music videos, only while the provider context is current                                                                                                                                           |
| `_artistsQueued(token, keys)`                                                              | Batch enqueue a shelf's favourite artists, one discography each, while the context is current                                                                                                                                                            |
| `_collectionsQueued(token, kind, keys)`                                                    | Batch enqueue a shelf's favourite playlists or mixes (`kind`), while the context is current                                                                                                                                                              |
| `_mediaRefetched(bucket, mediaId, token)`                                                  | Re-dispatch a download after fetching its evicted object, while the context is current                                                                                                                                                                   |
| `_queueRetryRefetched(bucket, mediaId, qid, token)`                                        | Retry the captured queue row only if the context and that row's refetch ownership remain current                                                                                                                                                         |
| `_queueTracksFetched(...)`                                                                 | Merge a track snapshot without racing live events                                                                                                                                                                                                        |
| `_folderTreeWarmed(source)`                                                                | Replay parked drill-ins after that source's folder sweep finishes                                                                                                                                                                                        |

The My Music slots name their source, so the doc's payload rule applies to
them too: `loadLibrary(source, category[, quiet])`,
`loadMoreLibrary(source, category)`, `setLibrarySort(source, category, order,
direction)`, `loadHome(source[, haveCached])`,
`openPlaylistFolder(source, folderId)`, the shelf DOWNLOAD ALL pairs
(`resolveFavoriteTracks/Albums/Artists/Playlists/Mixes/Videos(source)` for
the count behind the confirm, `downloadFavoriteTracks/Albums/Artists/
Playlists/Mixes/Videos(source)` for the bulk itself);
`myMusicSources()` /
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

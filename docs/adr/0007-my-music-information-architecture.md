# 0007: My Music distinguishes local files from account-saved shelves

- Status: accepted semantics; fixed layout/order/empty states superseded by ADR 0012
- Decided: 2026-09-16 (issue #213, the onboarding spec; rename and labels in #221/#258, generic sections in #259, the Library section in #222)
- Scope: the information architecture of the My Music pane
- Amended: 2026-10-03

## Decision

The home is **My Music**, not one account's page. Its local Library has
**Saved** (the files Waves saved, carrying actual provider provenance) and
**All files** (everything the configured folder scan sees; untagged files have
no invented provider badge). Provider account-saved shelves are separate
collections contributed by capable authenticated providers.

[ADR 0012](0012-composable-provider-surfaces.md) owns the accepted All home,
source filters, configurable shelves and compact setup prompts. It supersedes
this record's fixed Library-first layout, mandatory shelf ordering and old
empty-state presentation. Those QML changes are planned; Library and account
semantics remain in force.

The section list, the source labels and the empty-state choice are **bridge
data derived from provider capabilities and live sessions**, never QML
branches on a provider's name.

## Why

- "What is in my TIDAL account?" was the old home; a user who enabled only
  Apple had no surface reflecting what they own. Saved-first answers "what
  music do I have?", and the scan's All-files view answers "what is on
  disk?".
- Labels are information, not decoration: with one source they add nothing,
  with two they are the only way to tell a TIDAL save from an Apple one, and
  provenance badges already appear in search, so the numbers agree.
- Capability-driven visibility keeps the third provider cheap: it contributes
  a descriptor and a session, and the pane grows a section with no QML edit.

## Alternatives considered

- **Keep "My Tidal" and the account-first home**: rejected — a provider
  rename is exactly the one-provider thinking the spec removes.
- **Label every shelf always**: rejected — with one source the label is
  noise; the rule is "only when it informs".
- **A separate "Downloads" pane for saved files**: rejected in the design
  interview — saved files are music and belong in the same home as the rest
  of the user's music.
- **QML-side section rendering per provider**: rejected — identity branches
  duplicate the descriptor contract and require changes for each provider.

## Consequences

- The Saved view reads the scan's per-file item id and exposes it on the
  track row (#222): `waves/library/index.py` stores the value the download
  gate wrote (generic tag first, the legacy TIDAL id as fallback), and the
  provider badge is that id's namespace, so the ownership store keeps its
  existing role.
- The existing **saved shelves are per source**. The bridge answers a list of source groups (descriptor + the
  categories its capabilities can fill), each source renders its own label,
  strip and keep-alive panes, and every page loads through that source's
  provider, so a second FAVORITES provider appears with no QML edit. The
  pane's **Library section** (Saved and All files) currently sits
  above the source groups; the target order is configurable. It pages the scan's own file rows
  (`myMusicLibrary()` / `loadLibraryFiles(view)`) and is
  provider-independent by construction — no row comes from a provider
  fetch.
- A hand-edited provenance tag can misreport a file's source; the All-files
  view remains the honest fallback, and the limitation is documented.
- Tab, expanded-section and scroll positions survive the rename, so the
  change is invisible to an existing user.

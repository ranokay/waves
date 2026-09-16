# 0007: My Music puts the Library first, then source-labelled saved shelves

- Status: accepted
- Decided: 2026-09-16 (issue #213, the onboarding spec; rename and labels in #221/#258, generic sections staged in #259)
- Scope: the information architecture of the My Music pane

## Decision

The home surface is **My Music**, not one account's page. Its content, top
to bottom:

1. **The Library section**, always present, with two views: **Saved** as the
   default (the files Waves itself saved, carrying provider provenance) and
   **All files** second (everything the configured folder scan sees,
   untagged rows carrying no provider badge). With no library folder
   configured the section says how to point Waves at one instead of
   disappearing.
2. **Saved shelves**, one per provider that can fill them — an account
   library, so a provider contributes only while it has a live session. A
   shelf is **labelled by source only when more than one provider
   contributes** ("Saved from TIDAL"); with a single source the rows _are_
   that source and no label repeats it.
3. **Nothing else**: a section no enabled provider can fill is hidden, and a
   signed-out pane shows one provider-named empty state with the sign-in
   action rather than leaving dead tabs.

The section list, the source labels and the empty-state choice are **bridge
data derived from provider capabilities and live sessions**, never QML
branches on a provider's name.

This is the settled destination, not a description of every pane today: the
pane's first provider-shaped views are the starting point, and what remains
to move onto the rule is recorded under Consequences.

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
- **QML-side section rendering per provider**: rejected — the audit's
  identity branching (F-10) is what the descriptor contract (#214) removes.

## Consequences

- The Saved view needs the scan to expose each file's item id and
  provenance; that track-row addition is the implementation dependency of
  the Library section (staged after the rename and labels).
- While the Library section and the generic per-provider shelves land, the
  pane keeps its existing TIDAL-shaped views: the per-category tabs for a
  signed-in source and the signed-out empty state's TIDAL words. The ADR
  records the destination, the source-label rule is already the bridge data
  those renderers will read, and the remaining renderer work is tracked
  separately.
- A hand-edited provenance tag can misreport a file's source; the All-files
  view remains the honest fallback, and the limitation is documented.
- Tab, expanded-section and scroll positions survive the rename, so the
  change is invisible to an existing user.

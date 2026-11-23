import QtQuick
import "../../components"

// SHOW ALL / SHOW LESS toggle for a search-page list section (Albums,
// Tracks, Videos, Playlists, Mixes). Shows only in the mixed All view and
// only when the section has more than the 5 rows shown by default; clicking
// flips (and persists) that section's expanded flag on the unified results
// view.
// `host` is required by the ShowAllLabel base, which declares it; the
// toggle reads through it:
//   host.filterType / host.searchReveal
ShowAllLabel {
  property string section: ""
  property int cap: 5
  // The unified results view that owns the section's expanded map (and its
  // own neutral pref key).
  property var group: null
  opacity: host.searchReveal
  visible: host.filterType === "all" && count > cap
  onToggled: if (group !== null)
    group.toggleExpanded(section)
}

import QtQuick

// SHOW ALL / SHOW LESS toggle for a search-page list section (Albums,
// Tracks, Videos, Playlists, Mixes). Shows only in the mixed All view and
// only when the section has more than the 5 rows shown by default; clicking
// flips (and persists) that section's expanded flag on its own provider
// group (issue #292).
// `host` is required by the ShowAllLabel base, which declares it; the
// toggle reads through it:
//   host.filterType / host.searchReveal
// Split out of Main.qml (#315 slice 6).
ShowAllLabel {
  property string section: ""
  property int cap: 5
  // The provider group this section belongs to: the caller passes its
  // instance, so the toggle lands on the group's own expanded map (and
  // its own provider-keyed pref) and a collapsed group hides its SHOW
  // ALL with its rows.
  property var group: null
  opacity: host.searchReveal
  visible: (group === null || !group.collapsed) && host.filterType === "all" && count > cap
  onToggled: if (group !== null)
    group.toggleExpanded(section)
}

.pragma library
// The status-light colour vocabulary, shared by the header's per-provider
// marks (Main.qml) and the Settings status rows (SettingsPage.qml): accent is
// healthy, gold says be aware, red says needs attention, and anything else (a
// switched-off component) goes quiet. Both palettes expose the same token
// names, so one cascade keeps every small status dot in the app agreeing.
//   import "StatusLight.js" as StatusLight
//   color: StatusLight.colorFor(root, state)
function colorFor(palette, state) {
    if (state === "signed_in" || state === "runtime_ready") return palette.accent
    if (state === "not_signed_in" || state === "signed_out" || state === "not_set_up") return palette.gold
    if (state === "needs_attention") return palette.red
    return palette.textDim
}

pragma Singleton
import QtQuick

// The one source of truth for the phosphor-green accent. Every accent-tinted
// property binds to Palette.accent (qualified as Primitives.Palette.accent
// from other files), so a palette change lands in one place.
QtObject {
  readonly property color accent: "#3dff6e" // phosphor green (primary)
}

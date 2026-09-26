pragma Singleton
import QtQuick

// The one source of truth for the phosphor-green accent. Every accent-tinted
// property binds to Palette.accent (qualified as Primitives.Palette.accent
// from other files), so a palette change lands in one place. Values frozen:
// this only moves the literal, it never recolors anything.
QtObject {
  readonly property color accent: "#3dff6e" // phosphor green (primary)
}

pragma Singleton
import QtQuick

// The one source of truth for the phosphor-green accent. Every file that
// used to carry its own accent copy binds to Palette.accent instead,
// so a palette change lands in one place. Values frozen: this only moves
// the literal, it never recolors anything.
QtObject {
  readonly property color accent: "#3dff6e" // phosphor green (primary)
}

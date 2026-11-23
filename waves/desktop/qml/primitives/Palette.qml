pragma Singleton
import QtQuick

// Shared phosphor accent and legible secondary text. Components bind to these
// colors through Primitives.Palette so they stay consistent across surfaces.
QtObject {
  readonly property color accent: "#3dff6e" // phosphor green (primary)
  readonly property color textDim: "#858a95"
}

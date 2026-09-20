import QtQuick

// Old-school LED dot-matrix progress. Dots sit in a fixed grid and brighten
// (faded → bright) in a bottom-up, left-to-right "stacking" order as pct
// rises, each dot is a precise fraction of the whole.
// The palette values are local copies of Main.qml's static literals —
// the SettingsPage.qml convention; keep them in step if the palette changes. `ledPulse` / `shimmerPhase` stay host-bound
// (Main.qml's one shared 20 Hz pair), and `queueEdgeHeld` lets a drawer-edge
// drag defer the column-count settle; all three are required, so a missed
// binding fails at load instead of freezing the bar silently.
Item {
  id: dm
  property real pct: 0
  property int rows: 4
  property real dot: 3
  property real gap: 2
  property int maxCols: 0
  property bool pulse: true
  property color onColor: "#3dff6e"
  // Required, not defaulted: a missed host binding must fail at load rather
  // than silently freeze the bar at a lone instance's static state.
  required property real ledPulse
  required property real shimmerPhase
  required property bool queueEdgeHeld
  // "Finishing" twinkle: the bar sits at
  // 100% while the final steps run (merge, decrypt, FLAC extract,
  // tagging), so instead of freezing, every lit dot breathes on its
  // own pseudo-random offset of the shared shimmerPhase clock. Only
  // download surfaces set this; the player's scrub track is playback
  // position, not work, and must stay static at 100%.
  property bool finishing: false
  // The percentage, carved INTO the bar on demand rather than printed
  // beside it: `word`
  // ("37%") is spelled in a 3x5 dot font in the matrix's own cells,
  // centred, always lit, on a PLATE (the glyph box plus a cell of
  // margin) knocked back to near black whatever the bar under it is
  // doing, so the number reads the same at every percentage. Taking the
  // INVERSE of the bar under them instead (a hole where the bar is
  // lit, a lit dot where it is not) would read at either end of a run
  // and not at all while the fill edge crossed the digits: half the
  // number dark, half bright, for that whole stretch.
  // This polarity and not the other way up (dark digits on a lit
  // plate): a 3x5 glyph is mostly
  // stroke, so punched out of a plate it reads as a blob to be decoded
  // from its counters, worst of all on "100%". Lit strokes are the
  // polarity the font was drawn for.
  // `wordReveal` 0..1 fades it in; every cell moves from its bar state
  // to its digit state on its own pseudo-random delay (the "dissolve"),
  // so the number condenses out of the bar and dissolves back into it,
  // and a reveal that reverses mid-way plays back from wherever it is.
  // The zone is the WORD's own width, centred: one, two or three digits
  // all sit in the middle. A fixed four-glyph zone ("100%") with the
  // word right-aligned in it would move nothing on 9 -> 10 and 99 ->
  // 100, but would hang every ordinary reading off centre to the right
  // for the sake of the one percent of a run that is 100.
  // Needs five rows (a digit is five tall); with fewer, or no word, the
  // matrix is the plain bar.
  property string word: ""
  property real wordReveal: 0
  readonly property var font3x5: ({
      "0": ["111", "101", "101", "101", "111"],
      "1": ["010", "110", "010", "010", "111"],
      "2": ["111", "001", "111", "100", "111"],
      "3": ["111", "001", "111", "001", "111"],
      "4": ["101", "101", "111", "001", "001"],
      "5": ["111", "100", "111", "001", "111"],
      "6": ["111", "100", "111", "101", "111"],
      "7": ["111", "001", "001", "001", "001"],
      "8": ["111", "101", "111", "101", "111"],
      "9": ["111", "101", "111", "001", "111"],
      "%": ["101", "001", "010", "100", "101"]
    })
  // A glyph is five rows tall; in a taller grid it sits on the middle
  // five (the seven-row download face carries it on rows 1..5).
  readonly property bool wordOn: rows >= 5 && word !== "" && wordReveal > 0
  readonly property int wordZoneW: Math.max(0, word.length * 4 - 1)
  // Rounded, not floored: a cell is 4px and the ideal start lands on a
  // half cell whenever the leftover is odd, so rounding keeps the worst
  // case to half a cell either way instead of a whole one.
  readonly property int wordZoneStart: Math.round((cols - wordZoneW) / 2)
  readonly property int wordRowTop: Math.floor((rows - 5) / 2)
  // The plate the number sits on: the glyph box with a cell of margin
  // all round (on the seven-row face that is the full height), held at
  // this alpha, so no digit stroke ever touches a bar cell of its own
  // brightness. Not 0: a whisper of the grid keeps it a plate laid over
  // the bar rather than a hole cut out of the button.
  property real wordPlate: 0.04
  function wordPlateAt(col, rowTop) {
    return col >= wordZoneStart - 1 && col <= wordZoneStart + wordZoneW && rowTop >= wordRowTop - 1 && rowTop <= wordRowTop + 5
  }
  function wordOnAt(col, rowTop) {
    var z = col - wordZoneStart
    if (z < 0 || z >= wordZoneW || z % 4 === 3)
      return false
    var r = rowTop - wordRowTop
    if (r < 0 || r > 4)
      return false
    var g = font3x5[word.charAt(Math.floor(z / 4))]
    return g ? g[r].charAt(z % 4) === "1" : false
  }
  // Conveyor edge fade. Cells within edgeFadeW px of either end, or
  // edgeFadeH px of the top / bottom, fade out on the SAME curve as
  // ShelfEdgeFades and the LIP fades (darkness 1.0 @0, 0.82 @0.25,
  // 0.28 @0.6, 0 @1 of the fade), so a bar that runs to its outline
  // arrives and leaves like a shelf's cards at the shelf's end instead
  // of stopping hard. 0 = no fade (the queue row, the scrubbers).
  property real edgeFadeW: 0
  property real edgeFadeH: 0
  // Soft outer rows: each cell of the top row shades from `edgeSoft`
  // alpha at its outer (top) edge to full at its inner edge, the
  // bottom row mirrored, so the outermost blocks blend into whatever
  // the bar sits on instead of stopping at a hard line (the queue
  // row's bar, which has no outline to end at). -1 = off.
  property real edgeSoft: -1
  // Pad cells: the outermost padCols columns at either end and padRows
  // rows top and bottom are decoration. They draw as field, but take no
  // part in the fill (the fill runs over the inner fillCols x fillRows
  // only), so the edge fade above spends itself on cells that carry no
  // progress and the first real block lights a little further in,
  // where the fade has mostly let go. The fade to zero would otherwise
  // hide the opening several percent of a run entirely (a 56-track
  // playlist at 9 tracks would show an empty bar). With mirrorPads a
  // pad copies its nearest real neighbour's state rather than staying
  // dark, so a full bar's ends still light and fade like the unpadded
  // one; a pad never pulses.
  // 0 / 0 = no pads (the queue row, the scrubbers). Keep the count
  // small: the fill must still visibly start at the start of the bar.
  property int padCols: 0
  property int padRows: 0
  property bool mirrorPads: false
  readonly property int fillCols: Math.max(1, cols - 2 * padCols)
  readonly property int fillRows: Math.max(1, rows - 2 * padRows)
  readonly property int fillTotal: fillRows * fillCols
  readonly property Gradient softTop: Gradient {
    GradientStop {
      position: 0
      color: Qt.alpha(dm.onColor, Math.max(0, dm.edgeSoft))
    }
    GradientStop {
      position: 1
      color: dm.onColor
    }
  }
  readonly property Gradient softBottom: Gradient {
    GradientStop {
      position: 0
      color: dm.onColor
    }
    GradientStop {
      position: 1
      color: Qt.alpha(dm.onColor, Math.max(0, dm.edgeSoft))
    }
  }
  readonly property real gridW: cols * (dot + gap) - gap
  function edgeVis(t) {
    t = Math.max(0, Math.min(1, t))
    var d = t < 0.25 ? 1 - (t / 0.25) * 0.18 : t < 0.6 ? 0.82 - ((t - 0.25) / 0.35) * 0.54 : 0.28 - ((t - 0.6) / 0.4) * 0.28
    return 1 - d
  }
  // The column count follows a SETTLED width, not the live one. Cols
  // riding width directly meant a drawer-edge drag (which resizes per
  // mouse move) changed `total` on every pixel, and the Repeater tore
  // down and rebuilt every dot each time: thousands of object churns
  // per drag, a GUI event backlog, and a pointer that stayed wedged
  // for a beat after letting go. The bar tolerating a stale column
  // count for a beat is invisible; the churn was not.
  // 300ms, and never while the drawer edge is held: at 120ms the one
  // remaining rebuild landed mid-way through the grip's 220ms release
  // animation and visibly froze it (a plain click, changing nothing,
  // was smooth). Letting the release animation finish first moves the
  // same rebuild onto a static screen, where it cannot be seen.
  // Declared with a binding for a correct first paint, then the
  // imperative assignment below BREAKS that binding so a drag can no
  // longer ride it; from then on only the timer writes. The break is
  // deferred one event-loop turn past completion, NOT done in
  // onCompleted: a matrix is completed mid-cascade, before the sizes
  // around it have finished landing (the download button's Loader
  // builds it while the button is still the queued face's width, and
  // the button widens to the running width a binding or two later), so
  // breaking on completion latched that pre-layout width and the bar
  // opened with two columns too many for the settle interval, then
  // shed them. Every width write of the creating turn still rides the
  // binding; the timer takes over from the next turn on.
  property real _settledWidth: width
  Component.onCompleted: Qt.callLater(function () {
    if (dm)
      dm._settledWidth = dm.width
  })
  onWidthChanged: dmSettle.restart()
  Timer {
    id: dmSettle
    interval: 300
    onTriggered: if (dm.queueEdgeHeld)
      dmSettle.restart()
    else
      dm._settledWidth = dm.width
  }
  readonly property int cols: {
    var c = Math.max(1, Math.floor((_settledWidth + gap) / (dot + gap)))
    return (maxCols > 0 && c > maxCols) ? maxCols : c
  }
  readonly property int total: rows * cols
  readonly property int litCount: Math.round(Math.max(0, Math.min(100, pct)) / 100 * fillTotal)
  implicitHeight: rows * dot + (rows - 1) * gap
  Repeater {
    model: dm.total
    delegate: Rectangle {
      required property int index
      readonly property int col: index % dm.cols
      readonly property int rowTop: Math.floor(index / dm.cols)
      // column-major, bottom-up: fill one column from the bottom to the
      // top, then start the next column, like rising bars.
      // Position within the fill (pads excluded); a pad clamps to its
      // nearest real cell, which is what it mirrors when asked to.
      readonly property int fillCol: col - dm.padCols
      readonly property int fillRow: rowTop - dm.padRows
      readonly property bool pad: fillCol < 0 || fillCol >= dm.fillCols || fillRow < 0 || fillRow >= dm.fillRows
      readonly property int nearCol: Math.max(0, Math.min(dm.fillCols - 1, fillCol))
      readonly property int nearRow: Math.max(0, Math.min(dm.fillRows - 1, fillRow))
      readonly property int fillIndex: nearCol * dm.fillRows + (dm.fillRows - 1 - nearRow)
      readonly property bool lit: (!pad || dm.mirrorPads) && fillIndex < dm.litCount
      // the single next block pulses while a download is in progress
      readonly property bool pulsing: !pad && dm.pulse && fillIndex === dm.litCount && dm.litCount < dm.fillTotal
      // Per-dot pseudo-random phase offset for the finishing twinkle
      // (fract(sin(i)*const), the classic shader hash: cheap, stable,
      // uniform enough for eyes).
      readonly property real twinkleR: {
        var r = Math.sin(index * 12.9898) * 43758.5453
        return r - Math.floor(r)
      }
      x: col * (dm.dot + dm.gap)
      y: rowTop * (dm.dot + dm.gap)
      width: dm.dot
      height: dm.dot
      radius: 0   // sharp LED cells
      color: dm.onColor
      gradient: dm.edgeSoft < 0 ? null : rowTop === 0 ? dm.softTop : rowTop === dm.rows - 1 ? dm.softBottom : null
      // Breathe off the host's shared 20 Hz clock (`ledPulse`) rather than a
      // per-frame animation, so a running download doesn't repaint the
      // whole window every vsync. See Main.qml's ledPulse.
      readonly property real barOpacity: (dm.finishing && lit) ? 0.62 + 0.38 * (0.5 + 0.5 * Math.cos(2 * Math.PI * (dm.shimmerPhase * 2 + twinkleR))) : pulsing ? dm.ledPulse : (lit ? 1.0 : 0.16)
      // A cell of the word (a digit stroke) or of the plate behind
      // it: its own reveal is the shared one shifted by a per-cell
      // random delay (a second hash, so it does not line up with the
      // twinkle), and it lerps its bar state -> its carve state on
      // it. A stroke goes fully lit whatever the bar under it is
      // doing, the plate around it goes to near black, so the
      // number reads identically at 4% and at 96%.
      readonly property bool wordCell: dm.wordOn && dm.wordOnAt(col, rowTop)
      readonly property bool plateCell: dm.wordOn && !wordCell && dm.wordPlateAt(col, rowTop)
      readonly property real wordTo: wordCell ? 1.0 : dm.wordPlate
      readonly property real wordDelay: {
        var r = Math.sin(index * 78.233 + 1.7) * 43758.5453
        return (r - Math.floor(r)) * 0.65
      }
      readonly property real wordT: Math.max(0, Math.min(1, (dm.wordReveal - wordDelay) / 0.35))
      // Static per cell (its own position against the fade
      // lengths), so the fade costs nothing per tick.
      readonly property real edgeMul: (dm.edgeFadeW > 0 ? Math.min(dm.edgeVis((x + dm.dot / 2) / dm.edgeFadeW), dm.edgeVis((dm.gridW - x - dm.dot / 2) / dm.edgeFadeW)) : 1) * (dm.edgeFadeH > 0 ? Math.min(dm.edgeVis((y + dm.dot / 2) / dm.edgeFadeH), dm.edgeVis((dm.implicitHeight - y - dm.dot / 2) / dm.edgeFadeH)) : 1)
      opacity: edgeMul * ((wordCell || plateCell) ? barOpacity + (wordTo - barOpacity) * wordT : barOpacity)
    }
  }
}

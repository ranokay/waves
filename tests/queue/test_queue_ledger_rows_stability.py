"""The queue ledger's row model must not rebuild or rescroll on live ticks.

WHAT THIS FENCES OFF
--------------------
While a collection downloads, the backend streams per-track updates twice a
second (``queueTrackState`` on lifecycle changes, ``queueTrackPct`` from the
progress poll), and Main.qml replaces the row's track array with a fresh
same-length array on each one. Binding that array as the ledger's model tears
down and rebuilds every delegate per tick, which throws a scrolled list back
to the top and reads as the hover-peek sliver vibrating under the pointer.

HOW THIS STAYS FIXED
--------------------
The ledger's model is a ListModel of empty slots. ``syncRows`` appends or
removes only the difference when the slot count changes, and does nothing when
it does not. The slot count is an int derived from
``queueTracks[...].length``; a same-length tick re-evaluates the delegates'
own ``td`` bindings in place.

The behavior is proved on the real Main.qml by
``test_queue_ledger_scroll.py``: a scrolled 1207-track ledger keeps its built
delegates, its contentY and its first visible row across a live tick, repaints
the changed track in place, and holds its position when a track arrives live.
This module is the wiring pin for the shape that makes that possible.
"""

from __future__ import annotations

import re

from support.paths import QML_MAIN

# The ledger lives in QueueDrawer.qml, where both its ListView and the
# queueTracks counts live.
QUEUE_DRAWER_QML = QML_MAIN.parent / "domains/queue/QueueDrawer.qml"

# The ledger row delegate is the only thing that carries this name, so it is
# the anchor for finding the ledger's own model without pinning a line number.
LEDGER_ROW_MARKER = 'objectName: "qTrackTitle"'


def _ledger_model_line(src: str) -> str:
    """The `model:` binding of the ledger whose delegate is a track row."""
    head = src[: src.index(LEDGER_ROW_MARKER)]
    models = [line.strip() for line in head.splitlines() if re.match(r"^\s*model:", line)]
    assert models, (
        "no model binding found above the ledger row delegate in QueueDrawer.qml; if "
        "the queue track list moved, update this guard rather than deleting it"
    )
    return models[-1]


def test_wiring_the_ledger_model_is_a_slot_store_not_the_array():
    src = QUEUE_DRAWER_QML.read_text(encoding="utf-8")
    line = _ledger_model_line(src)

    assert "host.queueTracks[" not in line, (
        "the queue track list binds host.queueTracks rows directly as its model again; "
        f"every live tick replaces that array, which rebuilds every delegate: {line}"
    )
    assert re.search(r"model:\s*ListModel\b", line), (
        f"the ledger's model is not a ListModel slot store, so this guard can no longer read it: {line}"
    )
    assert re.search(r"readonly property int wantRows:\s*qrow\.ledgerSlots\b", src), (
        "the ledger's slot count is not the int qrow.ledgerSlots; a non-int model is an array model"
    )
    assert re.search(r"readonly property int ledgerSlots:", src), (
        "qrow.ledgerSlots is not declared `readonly property int`, so it cannot be a count"
    )
    # Incremental sync: append or remove only the difference, never clear.
    assert "ledgerRows.append(" in src and "ledgerRows.remove(" in src, (
        "syncRows no longer grows/shrinks the slot store by the difference"
    )
    assert "ledgerRows.clear(" not in src, "the ledger clears its slots instead of removing only the tail"


def test_wiring_every_count_taken_from_queue_tracks_uses_length():
    """Whatever feeds the slot count must count rows, not carry them."""
    src = QUEUE_DRAWER_QML.read_text(encoding="utf-8")
    counts = [
        line.strip()
        for line in src.splitlines()
        if re.match(r"^\s*(?:model:|readonly property int \w+:)", line) and "host.queueTracks[" in line
    ]
    assert counts, (
        "nothing derives a count from host.queueTracks in QueueDrawer.qml any more; "
        "if the queue track list moved, update this guard rather than deleting it"
    )
    for line in counts:
        assert ".length" in line, (
            "a queue-track count binds the rows array itself rather than its "
            f"length, so the delegates rebuild whenever a tick replaces it: {line}"
        )

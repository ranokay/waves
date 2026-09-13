"""JS handed to QML scenarios that need to walk the live object tree.

``findFirst`` matches a predicate; ``findObject`` matches an objectName. Both
descend through a Loader's ``item`` and a Popup's ``contentItem``, so a mark
inside a loaded popup is reachable from the scene root.
"""

from __future__ import annotations

FINDER_JS = """
function findFirst(it, predicate) {
    if (!it) return null;
    if (predicate(it)) return it;
    if (it.item) {
        var loaded = findFirst(it.item, predicate);
        if (loaded) return loaded;
    }
    if (it.contentItem) {
        var content = findFirst(it.contentItem, predicate);
        if (content) return content;
    }
    var kids = it.children || [];
    for (var i = 0; i < kids.length; i++) {
        var hit = findFirst(kids[i], predicate);
        if (hit) return hit;
    }
    return null;
}
function findObject(it, name) {
    return findFirst(it, function (o) { return o.objectName === name; });
}
"""


def scene_js(body: str) -> str:
    """Wrap a JS body run against the scene in an IIFE with the finders."""
    return "(function () {" + FINDER_JS + body + "})()"

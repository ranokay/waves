"""Namespaced string ids (§4.2 of the provider spec): "tidal:123", "apple:456".

One format everywhere new -- ownership rows, on-disk tags, queue rows -- so a
second provider can share the numeric id space without the two owners'
answers bleeding into each other. The module is deliberately standard-library
only (no Qt, no tidalapi): the ownership store and the tag writer both live
below the UI stack, and the one convention must be importable from the
deepest layer that speaks ids.

A bare id -- what every build before the namespace wrote -- reads as tidal
(the DEFAULT_PROVIDER), which is what keeps a TIDAL-only library's every
existing query and every existing file answered.
"""

DEFAULT_PROVIDER = "tidal"


def namespaced_id(value) -> str:
    """An id in the namespaced spelling; a bare value reads as tidal.

    A value that already carries a namespace ("tidal:123", "apple:456") passes
    through untouched -- never "tidal:tidal:..."; a bare value gains the
    default provider's prefix, the spec's own "legacy bare ids read as tidal"
    rule. Empty stays empty: no id is no id, never a bare namespace.
    """
    text = str(value or "")
    provider, sep, raw = text.partition(":")
    if sep and provider and raw:
        return text
    return f"{DEFAULT_PROVIDER}:{text}" if text else ""

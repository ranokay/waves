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


def provider_of_id(value) -> str:
    """The provider namespace a media id carries, or "" when it carries none.

    The namespace spelling's own reader, built on ``namespaced_id``'s rule: a
    bare legacy id reads as the default provider, an id that already carries a
    namespace passes through, and an empty value answers "". A caller that must
    not guess -- a badge renders no mark for a namespace nobody claimed --
    checks the provider registry on top of this.
    """
    text = str(value or "")
    if not text:
        return ""
    return namespaced_id(text).partition(":")[0]


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


def download_identity_id(media) -> str:
    """The id a downloaded file is filed under, which is not always ``media.id``.

    A Waves 'best of both' merge fetches a track from one edition and lands it in
    another edition's folder, so it carries ``waves_identity_id``: the id the
    whole app (queue rows, ownership, collection membership) keys that download
    by, while ``media.id`` stays the source stream being fetched. Stamping the
    source id into the file meant a later plain job over the same folder asked
    about the identity id, failed to recognise Waves' own file, and wrote a
    ``_01`` duplicate beside it instead of replacing it.

    Args:
        media: The track or video being written.

    Returns:
        str: The identity id when the item carries one, else its own id, else "".
    """
    return str(getattr(media, "waves_identity_id", "") or getattr(media, "id", "") or "")


def credited_artist_ids(media) -> list[str]:
    """Raw provider ids for the artists credited on ``media``, in credited order.

    The identity half of the artist NAMES written beside them. Two artists can
    share a name, so a file tagged only with the name cannot later say which of
    them it belongs to (and neither can the folder it sits in). Id-less stubs
    are dropped rather than written blank: a missing id means unknown, and
    unknown must never read as somebody else.

    Args:
        media: The track or video being written.

    Returns:
        list[str]: The credited artists' ids, possibly empty.
    """
    return [str(a.id) for a in getattr(media, "artists", None) or [] if getattr(a, "id", None)]


def owned_item_ids(media) -> set[str]:
    """Every item id a file on disk may legitimately carry for ``media``.

    Normally just its own id. A best-of-both member is filed under the identity
    edition (see :func:`download_identity_id`), but every build up to v0.1.21 wrote the
    SOURCE edition's id into that same file, so libraries assembled by an older
    Waves are full of merged tracks tagged the other way. Recognising both means
    a forced re-save replaces its own file, and re-tags it with the identity id
    on the way, instead of leaving a numbered duplicate beside it that the app
    will never delete.

    Args:
        media: The track or video being written.

    Returns:
        set[str]: The ids this download may treat as its own copy.
    """
    ids = (getattr(media, "waves_identity_id", ""), getattr(media, "id", ""))
    return {str(i) for i in ids if i}

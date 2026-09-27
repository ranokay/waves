"""Implementation helpers shared by the download engine and the providers.

The seam's rule, one way: the engine (``waves.download``) and every provider
package import from here; this module imports from neither. Standard library
plus ``requests``/``certifi``/``urllib3`` only -- never tidalapi, Qt or the
bridge -- so a provider stays importable without the engine and the engine
stays importable without any provider SDK.

Qualifying contents: a helper the engine used to own that a provider also
needs (item identity, refusal parsing, HTTP pooling). Provider-specific
bodies and engine-only policy stay where they are.

Allowed import direction, one way: providers import the neutral vocabulary
(``waves.providers.base``), shared metadata helpers (``waves.metadata``) and
this module -- never the engine (``waves.download``), the bridge, or another
provider. The engine imports this module and the seam; nothing here imports
either of them back, which is what keeps every provider importable without
the engine.

``waves.download`` re-exports these names (``from waves.providers.shared
import ...``), so the suite's existing ``waves.download.<name>`` patch and
import targets keep resolving to the same objects.
"""

from __future__ import annotations

import certifi
import requests
from requests.adapters import HTTPAdapter, Retry
from requests.exceptions import HTTPError
from urllib3.util.ssl_ import create_urllib3_context

# TIDAL's subStatus family for "your session, not the content": 11001 user not
# authorised, 11002 invalid token, 11003 expired token. A 401 carrying one of
# these is a login problem and must never be read as "this track is gone".
_TIDAL_SUBSTATUS_AUTH_MIN: int = 11000
_TIDAL_SUBSTATUS_AUTH_MAX: int = 11999


def _tidal_refuses_asset(error: HTTPError) -> str | None:
    """TIDAL's own words when it refuses to serve an item, or None if this is
    something else (a network hiccup, a dead session, a server error).

    The playback-info endpoint answers a track the account cannot play with a
    401 or 403 whose body says why (observed: ``subStatus 4005 "Asset is not
    ready for playback"`` for tracks greyed out in the official apps). The
    same 401 status also announces an expired or invalid token, so the body is
    the only way to tell "TIDAL will not give you this track" from "TIDAL does
    not know who you are"; tidalapi already retried the expired-token case
    once with a refresh, so what reaches here is whatever survived that.

    Args:
        error (HTTPError): The requests error raised for the playback request.

    Returns:
        str | None: TIDAL's user message (or a generic one) when this is a
            refusal of the asset itself, None otherwise.
    """
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status not in (401, 403):
        return None
    body: dict = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except Exception:  # noqa: S110  # a body that is not JSON is still a refusal
        pass
    message = str(body.get("userMessage") or "")
    if message.startswith("The token has expired"):
        return None
    sub_status = body.get("subStatus")
    if isinstance(sub_status, int) and _TIDAL_SUBSTATUS_AUTH_MIN <= sub_status <= _TIDAL_SUBSTATUS_AUTH_MAX:
        return None
    return message or f"HTTP {status}"


def _waves_item_id(media) -> str:
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


def _artist_ids(media) -> list[str]:
    """TIDAL ids for the artists credited on ``media``, in credited order.

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


def _waves_owned_ids(media) -> set[str]:
    """Every item id a file on disk may legitimately carry for ``media``.

    Normally just its own id. A best-of-both member is filed under the identity
    edition (see :func:`_waves_item_id`), but every build up to v0.1.21 wrote the
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


class _SharedContextAdapter(HTTPAdapter):
    """HTTPAdapter that gives every pooled connection one shared, preloaded
    SSLContext.

    requests' default cert_verify hands urllib3 a CA bundle *path* per
    connection, and urllib3 then builds a fresh SSLContext and re-parses the
    whole certifi PEM corpus (~150 certificates) on every TLS connect. That
    work runs GIL-free in OpenSSL, so a burst of cold connections saturates
    every core (the CPU spike at download start, worst on modest Windows
    boxes). Loading certifi once and sharing the context leaves only the
    handshake itself per connection, which is a few milliseconds.
    """

    def __init__(self, ssl_context, **kwargs) -> None:
        self._ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)

    def cert_verify(self, conn, url, verify, cert) -> None:
        # For the default verify=True case, do NOT set conn.ca_certs: that is
        # what triggers urllib3's per-connection load_verify_locations(). The
        # shared context already carries certifi and CERT_REQUIRED, so
        # verification stays fully on. Custom verify paths or client certs
        # fall back to the stock (slower, per-connection) behaviour.
        if verify is True and cert is None:
            return
        super().cert_verify(conn, url, verify, cert)


def pooled_session(
    pool_connections: int = 10,
    pool_maxsize: int = 10,
    pool_block: bool = False,
    max_retries: Retry | int = 0,
) -> requests.Session:
    """Build a keep-alive session whose connections share one preloaded
    SSLContext (see _SharedContextAdapter). Callers own the pool and retry
    policy; the download engine's process-wide instance lives in
    Download._shared_http()."""
    ssl_context = create_urllib3_context()
    ssl_context.load_verify_locations(certifi.where())
    session = requests.Session()
    adapter = _SharedContextAdapter(
        ssl_context,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        pool_block=pool_block,
        max_retries=max_retries,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

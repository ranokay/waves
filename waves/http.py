"""Pooled HTTP sessions with a shared TLS context and caller-owned retry policy.

Used by provider fetches, engine segments and preview probes. This module has
no provider SDK, engine or UI dependencies.
"""

from __future__ import annotations

import certifi
import requests
from requests.adapters import HTTPAdapter, Retry
from urllib3.util.ssl_ import create_urllib3_context


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

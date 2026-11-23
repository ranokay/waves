"""Pooled HTTP sessions with a shared TLS context and caller-owned retry policy.

Used by provider fetches, engine segments and preview probes. This module has
no provider SDK, engine or UI dependencies.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time

import certifi
import requests
from requests.adapters import HTTPAdapter, Retry
from urllib3.util.ssl_ import create_urllib3_context

logger = logging.getLogger("waves.http")


class IdleDropAdapter(HTTPAdapter):
    """Drop waiting keep-alives after an idle gap or sleep before reuse.

    This avoids urllib3's dead-socket probe, which crashed a packaged macOS
    build after wake. Checked-out connections keep their pools; replacing
    each removed slot lets blocking workers open fresh connections.
    """

    idle_reset_sec = 60.0
    sleep_gap_sec = 5.0

    def __init__(self, *args, **kwargs) -> None:
        self._drop_lock = threading.Lock()
        self._last_wall = time.time()
        self._last_mono = time.monotonic()
        super().__init__(*args, **kwargs)

    def _stale_since(self, wall0: float, mono0: float) -> str:
        wall = time.time() - wall0
        mono = time.monotonic() - mono0
        # macOS monotonic time pauses during sleep; wall time includes it.
        if wall - mono > self.sleep_gap_sec:
            return "sleep"
        if wall > self.idle_reset_sec:
            return "idle"
        return ""

    def _drop_pooled_connections(self) -> None:
        for manager in (self.poolmanager, *self.proxy_manager.values()):
            for key in list(manager.pools.keys()):
                pool = None
                with contextlib.suppress(KeyError):
                    pool = manager.pools[key]
                slots = getattr(pool, "pool", None)
                if slots is None:
                    continue
                # urllib3 uses a LIFO Queue. Detach the whole waiting set
                # atomically: a concurrent return must not hide an older
                # socket beneath itself during a bounded pop/put sweep.
                with slots.mutex:
                    waiting = list(slots.queue)
                    slots.queue.clear()
                    slots.queue.extend([None] * len(waiting))
                    slots.not_empty.notify_all()
                # close() may block or return another worker's connection;
                # it must run after the queue lock has been released.
                for connection in waiting:
                    if connection is not None:
                        try:
                            connection.close()
                        except Exception:
                            logger.debug("Detached HTTP connection could not close", exc_info=True)

    def send(self, request, *args, **kwargs):
        wall0, mono0 = time.time(), time.monotonic()
        with self._drop_lock:
            why = self._stale_since(self._last_wall, self._last_mono)
            if why:
                logger.info("HTTP pool stale after %s; dropping waiting connections", why)
                self._drop_pooled_connections()
            self._last_wall, self._last_mono = wall0, mono0
        try:
            return super().send(request, *args, **kwargs)
        finally:
            with self._drop_lock:
                # Finishing a request across sleep cannot make the waiting
                # keep-alives fresh, even if no other request has arrived.
                if self._stale_since(wall0, mono0) == "sleep":
                    self._drop_pooled_connections()
                self._last_wall, self._last_mono = time.time(), time.monotonic()


class _SharedContextAdapter(IdleDropAdapter):
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

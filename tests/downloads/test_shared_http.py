"""The segment-download HTTP session is process-wide (Download._shared_http):
a per-instance session meant a cold connection pool for every queued album, so
each album start paid its TLS setup all at once (an all-core CPU spike per
click of Download, worst on modest Windows boxes).

Two properties keep that spike gone and must not regress:

1. Every connection shares ONE preloaded SSLContext. requests' default
   cert_verify hands urllib3 a CA bundle path per connection, which makes
   urllib3 build a fresh SSLContext and re-parse the whole certifi corpus on
   every TLS connect. _SharedContextAdapter suppresses that path.
2. The pool is small and blocking (pool_block=True, _HTTP_POOL_MAXSIZE), so a
   cold start opens at most _HTTP_POOL_MAXSIZE connections concurrently no
   matter how many segment worker threads are running.
"""

from __future__ import annotations

import queue
import time

import pytest
import requests
import tidalapi

from waves.config import harden_api_session
from waves.download import Download
from waves.http import _SharedContextAdapter, pooled_session


@pytest.fixture(autouse=True)
def _reset_shared_session():
    """Isolate each test from the process-wide singleton."""
    Download._http_shared = None
    yield
    Download._http_shared = None


def test_same_session_across_calls():
    s1 = Download._shared_http()
    s2 = Download._shared_http()
    assert s1 is s2


def test_both_schemes_mounted_with_shared_context_adapter():
    s = Download._shared_http()
    https = s.get_adapter("https://example.com")
    http = s.get_adapter("http://example.com")
    assert isinstance(https, _SharedContextAdapter)
    assert isinstance(http, _SharedContextAdapter)


def test_pool_is_small_and_blocking():
    """Worker threads beyond the cap must queue for a free connection, not
    each open (and TLS-handshake) their own."""
    adapter = Download._shared_http().get_adapter("https://example.com")
    assert adapter._pool_maxsize == Download._HTTP_POOL_MAXSIZE
    assert adapter._pool_block is True


def test_one_ssl_context_shared_by_all_pools():
    """The preloaded context must reach urllib3's pools so connections skip
    the per-connection SSLContext build + certifi re-parse."""
    adapter = Download._shared_http().get_adapter("https://example.com")
    pool = adapter.poolmanager.connection_from_host("example.com", 443, scheme="https")
    assert pool.conn_kw.get("ssl_context") is adapter._ssl_context
    # Certifi is loaded: the context can actually verify (non-empty CA store).
    assert adapter._ssl_context.cert_store_stats()["x509_ca"] > 0


def test_cert_verify_skips_ca_path_for_default_verify():
    """Setting conn.ca_certs is exactly what triggers urllib3's
    load_verify_locations per connection; the default verify=True path must
    leave it alone."""

    class _Conn:
        pass

    adapter = Download._shared_http().get_adapter("https://example.com")
    conn = _Conn()
    adapter.cert_verify(conn, "https://example.com", verify=True, cert=None)
    assert not hasattr(conn, "ca_certs")


def test_pooled_session_defaults_fail_fast():
    """pooled_session() serves latency-sensitive one-shot callers (the video
    bandwidth probe): shared preloaded context, but single-attempt and
    non-blocking, unlike the download engine's retrying, blocking pool."""
    s = pooled_session()
    adapter = s.get_adapter("https://example.com")
    assert isinstance(adapter, _SharedContextAdapter)
    assert adapter._pool_block is False
    assert adapter.max_retries.total == 0
    assert adapter._ssl_context.cert_store_stats()["x509_ca"] > 0


def test_cert_verify_falls_back_for_custom_verify(tmp_path):
    """A custom CA bundle path must still go through the stock requests
    behaviour (correctness beats the fast path)."""
    import certifi

    adapter = Download._shared_http().get_adapter("https://example.com")

    class _Conn:
        pass

    conn = _Conn()
    adapter.cert_verify(conn, "https://example.com", verify=certifi.where(), cert=None)
    assert conn.ca_certs == certifi.where()


class _Clock:
    def __init__(self, monkeypatch):
        self.wall = 1000.0
        self.mono = 10.0
        monkeypatch.setattr(time, "time", lambda: self.wall)
        monkeypatch.setattr(time, "monotonic", lambda: self.mono)

    def advance(self, seconds, *, asleep=False):
        self.wall += seconds
        if not asleep:
            self.mono += seconds


class _Connection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _waiting_connection(adapter, *, proxy=False):
    manager = adapter.proxy_manager_for("http://proxy.example:8080") if proxy else adapter.poolmanager
    pool = manager.connection_from_host("example.com", 443, scheme="https")
    pool.pool.get(block=False)
    connection = _Connection()
    pool.pool.put(connection, block=False)
    return pool, connection


@pytest.mark.parametrize("session_kind", ["media", "catalog"])
@pytest.mark.parametrize("gap,asleep,stale", [(61, False, True), (10, True, True), (30, False, False)])
def test_idle_and_sleep_drop_waiting_connections_without_changing_request_policy(
    monkeypatch, session_kind, gap, asleep, stale
):
    clock = _Clock(monkeypatch)
    if session_kind == "catalog":
        session = tidalapi.Session.__new__(tidalapi.Session)
        session.request_session = requests.Session()
        harden_api_session(session)
        adapter = session.request_session.get_adapter("https://example.com")
    else:
        adapter = pooled_session(pool_maxsize=2, pool_block=True).get_adapter("https://example.com")
    pool, connection = _waiting_connection(adapter)
    requests_seen = []

    def send(_adapter, request, *args, **kwargs):
        requests_seen.append(kwargs)
        return "sent"

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    clock.advance(gap, asleep=asleep)
    assert adapter.send("request") == "sent"
    assert connection.closed is stale
    assert pool.pool.qsize() == pool.pool.maxsize
    if stale:
        assert all(slot is None for slot in pool.pool.queue)
    if session_kind == "catalog":
        assert requests_seen[0]["timeout"]
        assert adapter.max_retries.total > 0
    else:
        assert adapter._pool_block is True
        assert adapter.max_retries.total == 0
        assert adapter._ssl_context.cert_store_stats()["x509_ca"] > 0


def test_sleep_drops_proxy_connections_too(monkeypatch):
    clock = _Clock(monkeypatch)
    adapter = pooled_session(pool_maxsize=2).get_adapter("https://example.com")
    direct_pool, direct = _waiting_connection(adapter)
    proxy_pool, proxied = _waiting_connection(adapter, proxy=True)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", lambda *_args, **_kwargs: "sent")
    clock.advance(20, asleep=True)
    adapter.send("request")
    assert direct.closed and proxied.closed
    assert direct_pool.pool.qsize() == proxy_pool.pool.qsize() == 2


@pytest.mark.parametrize("another_request", [False, True])
def test_request_in_flight_across_sleep_does_not_make_waiting_connections_fresh(monkeypatch, another_request):
    clock = _Clock(monkeypatch)
    adapter = pooled_session(pool_maxsize=2, pool_block=True).get_adapter("https://example.com")
    pool, waiting = _waiting_connection(adapter)
    checked_out = pool.pool.get(block=False)
    seen = []

    def send(_adapter, request, *args, **kwargs):
        if request == "before-sleep":
            clock.advance(20, asleep=True)
            if another_request:
                adapter.send("after-wake")
        seen.append(request)
        return "sent"

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    # One real connection is checked out; only the other waits in the pool.
    pool.pool.get(block=False)
    pool.pool.put(_Connection(), block=False)
    waiting = pool.pool.queue[-1]
    adapter.send("before-sleep")
    assert waiting.closed
    assert not checked_out.closed
    assert pool.pool.qsize() == 1
    assert seen == (["after-wake", "before-sleep"] if another_request else ["before-sleep"])
    pool.pool.put(checked_out, block=False)
    assert pool.pool.qsize() == 2


def test_drop_returns_slots_for_a_blocking_worker(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    _Clock(monkeypatch)
    adapter = pooled_session(pool_maxsize=1, pool_block=True).get_adapter("https://example.com")
    pool, checked_out = _waiting_connection(adapter)
    assert pool.pool.get(block=False) is checked_out
    started = Event()

    def waiting_worker():
        started.set()
        return pool.pool.get(timeout=1)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(waiting_worker)
        assert started.wait(timeout=1)
        # A different pool has a stale waiting connection. Eviction must
        # preserve its slot, while the checked-out pool stays usable.
        other = adapter.poolmanager.connection_from_host("other.example", 443, scheme="https")
        other.pool.get(block=False)
        stale = _Connection()
        other.pool.put(stale, block=False)
        adapter._drop_pooled_connections()
        assert stale.closed
        assert other.pool.get(block=False) is None
        pool.pool.put(checked_out, block=False)
        assert future.result(timeout=1) is checked_out
    assert not checked_out.closed
    with pytest.raises(queue.Empty):
        pool.pool.get(block=False)

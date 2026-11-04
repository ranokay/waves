"""The MusicBrainz arbiter's real HTTP edge verifies against certifi.

The arbiter's fetch is injectable, so the existing arbiter suite never touches
urllib. These cases drive the default ``_http_fetch`` itself: it must hand
urllib the shared certifi-backed context, keep an HTTPError's status, and let
any other failure read as transient at the arbiter boundary.
"""

from __future__ import annotations

import urllib.error
import urllib.request

from waves.metadata.mb_arbiter import MBArbiter
from waves.tls import tls_context

WANT = {"title": "Album", "artist": "Artist", "year": "", "tracks": 12, "duration": 0}
LOCAL = {"tracks": 12, "runtime": 2400, "year": ""}


class _Response:
    status = 200

    def __init__(self, body: bytes = b"{}") -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc) -> bool:
        return False


def test_http_fetch_passes_the_shared_tls_context(monkeypatch):
    seen = {}

    def fake_urlopen(req, *, timeout=None, context=None):
        seen["context"] = context
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    status, body = MBArbiter(":memory:")._http_fetch("https://musicbrainz.org/ws/2/release/?fmt=json")
    assert (status, body) == (200, '{"ok": true}')
    assert seen["context"] is tls_context()


def test_http_fetch_keeps_an_http_error_status(monkeypatch):
    def fake_urlopen(req, *, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert MBArbiter(":memory:")._http_fetch("https://musicbrainz.org/ws/2/release/x") == (404, "")


def test_a_non_http_failure_stays_transient(monkeypatch):
    attempts = []

    def fake_urlopen(req, *, timeout=None, context=None):
        attempts.append(req.full_url)
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    arb = MBArbiter(":memory:", sleep=lambda _s: None)
    assert arb.arbitrate(WANT, LOCAL) is None
    assert attempts, "the arbitration never reached the HTTP edge"

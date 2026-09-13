"""Issue #39: a pasted title with a line break never reached TIDAL as typed.

Two backend rules behind ``WavesBridge.search``:

* every run of whitespace in the query collapses to one space before it is
  sent, so a multi-line paste searches the words the field shows, and
* a fetch that raises reports "Search failed", never "0 results" (which read
  as a search that found nothing), emits nothing and caches nothing, so a
  stale page already painted stays.

The wire lives on the fake provider (the search pipeline reads through the
Provider seam), so a failed fetch is the provider's own search raising.
"""

from __future__ import annotations

from types import SimpleNamespace

from support.search_fakes import (
    SearchStub as _Stub,
)
from support.search_fakes import (
    search_payload as _payload,
)
from support.search_fakes import (
    search_payloads as _payloads,
)

from waves.providers import Capability
from waves.waves_ui.backend import _STALE_STAMP


def _provider(search):
    return SimpleNamespace(name="TIDAL", capabilities=frozenset({Capability.SEARCH}), search=search)


def test_interior_whitespace_collapses_before_the_wire():
    sent = []
    stub = _Stub()
    stub.providers = {"tidal": _provider(lambda needle: sent.append(needle) or {"artists": [], "albums": []})}
    stub.search("  Le Guinness World Record\nSoft Power\tgonzales  ")
    assert sent == ["Le Guinness World Record Soft Power gonzales"]


def _boom(needle):
    raise RuntimeError("network down")


def test_a_raised_fetch_reports_failure_not_zero_results():
    stub = _Stub()
    stub.providers = {"tidal": _provider(_boom)}
    stub.search("needle")
    assert stub.statuses[-1] == "Search failed"
    assert not any(s.endswith(" results") for s in stub.statuses)
    assert stub.busy[-1] is False
    assert stub.searchResults.emits == []
    assert stub.saves == 0 and "needle" not in stub._search_cache


def test_a_raised_fetch_keeps_the_stale_page():
    stub = _Stub()
    stub.providers = {"tidal": _provider(_boom)}
    stub._search_cache["tidal:needle"] = (_STALE_STAMP, _payload(("al1",)))
    stub.search("needle")
    emitted = _payloads(stub)
    assert len(emitted) == 1 and "refresh" not in emitted[0], "only the stale page, nothing replaces it"
    assert stub.statuses[-1] == "Search failed"
    assert stub._search_cache["tidal:needle"][0] == _STALE_STAMP

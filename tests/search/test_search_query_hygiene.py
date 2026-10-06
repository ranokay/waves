"""A pasted title with a line break never reaches TIDAL as typed.

Two backend rules behind ``WavesBridge.search``:

* every run of whitespace in the query collapses to one space before it is
  sent, so a multi-line paste searches the words the field shows, and
* a fetch that raises reports the provider's own safe words, never "0
  results" (which read as a search that found nothing). The failed source
  shows them and nothing is cached, so a stale page already painted stays.

The wire lives on the fake provider (the search pipeline reads through the
Provider seam), so a failed fetch is the provider's own search raising.
"""

from __future__ import annotations

from types import SimpleNamespace

from search.fakes import (
    SearchStub as _Stub,
)
from search.fakes import (
    search_payload as _payload,
)
from search.fakes import (
    search_payloads as _payloads,
)

from waves.desktop.backend import _STALE_STAMP
from waves.providers import Capability


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


def test_a_lone_raised_fetch_reports_a_safe_summary_not_zero_results():
    # A lone enabled provider's failure names itself with the owner's safe
    # summary, never a silent "Search failed" with a blank page; nothing is
    # cached and busy is released. The page-count line still never says
    # "N results".
    stub = _Stub()
    stub.providers = {"tidal": _provider(_boom)}
    stub.search("needle")
    assert stub.statuses[-1] == "The operation could not finish. Try again or open the logs."
    assert not any(s.endswith(" results") for s in stub.statuses)
    assert stub.busy[-1] is False
    (payload,) = _payloads(stub)
    assert payload["sources"][0]["state"] == "failed"
    assert payload["sources"][0]["error"] == "The operation could not finish. Try again or open the logs."
    assert stub.saves == 0 and "needle" not in stub._search_cache


def test_a_raised_fetch_keeps_the_stale_page():
    stub = _Stub()
    stub.providers = {"tidal": _provider(_boom)}
    stub._search_cache["tidal:needle"] = (_STALE_STAMP, _payload(("al1",)))
    stub.search("needle")
    emitted = _payloads(stub)
    assert [a["id"] for a in emitted[-1]["sections"]["albums"]] == ["al1"], "the rows it had stay"
    assert emitted[-1]["sources"][0]["state"] == "failed" and emitted[-1]["sources"][0]["error"] != ""
    # The page holds rows, so the failure never blanks it; the source carries
    # the provider's own words instead of a generic "Search failed".
    assert stub.statuses[-1] == emitted[-1]["sources"][0]["error"]
    assert stub._search_cache["tidal:needle"][0] == _STALE_STAMP

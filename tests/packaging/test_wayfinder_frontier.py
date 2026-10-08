"""The frontier report names the issue an agent may take next.

`mise run frontier` replaces a per-issue `gh issue view` sweep: the first
open, unassigned `ready-for-agent` child with every blocker closed is the
frontier, a map with none ready names what it waits on, and checklist entries
that disagree with the tracker are listed for the delivering run to correct.
These drive the report on hand-built GraphQL payloads, with `gh` faked; no
network.
"""

from __future__ import annotations

import importlib.util
import json
import sys

from support.paths import REPO_ROOT


def _frontier_module():
    spec = importlib.util.spec_from_file_location("wayfinder_frontier", REPO_ROOT / "tools" / "wayfinder_frontier.py")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve the module's annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _node(number, *, state="OPEN", assignees=(), labels=("ready-for-agent",), blockers=()):
    return {
        "number": number,
        "title": f"Child {number}",
        "state": state,
        "assignees": {"nodes": [{"login": login} for login in assignees]},
        "labels": {"nodes": [{"name": name} for name in labels]},
        "blockedBy": {"nodes": [{"number": n, "state": s} for n, s in blockers]},
    }


def _issue(*nodes, body=""):
    return {"number": 1, "title": "Map", "body": body, "subIssues": {"nodes": list(nodes)}}


def _report(module, *nodes, body=""):
    return module.report(module.WayfinderMap.from_issue(_issue(*nodes, body=body)))


def test_the_first_ready_child_in_map_order_is_the_frontier():
    module = _frontier_module()

    lines = _report(module, _node(10, state="CLOSED"), _node(11, blockers=[(10, "CLOSED")]), _node(12))

    assert "  frontier: #11 Child 11" in lines
    assert "  also ready: #12 Child 12" in lines


def test_a_map_with_nothing_ready_names_what_it_waits_on():
    module = _frontier_module()

    lines = _report(
        module,
        _node(20, assignees=["ranokay"], labels=["ready-for-human"]),
        _node(21, blockers=[(20, "OPEN")]),
        _node(22, assignees=["someone"]),
        _node(23, labels=["needs-triage"]),
        _node(24, labels=["ready-for-agent", "ready-for-human"]),
    )

    assert "  frontier: none ready for an agent" in lines
    assert "    #20 needs a human (ranokay): Child 20" in lines
    assert "    #22 claimed (someone): Child 22" in lines
    assert "    #23 not labelled ready-for-agent: Child 23" in lines
    assert "    #24 needs a human: Child 24" in lines
    assert "    #21 blocked by #20: Child 21" in lines


def test_checklist_entries_that_disagree_with_the_tracker_are_reported():
    module = _frontier_module()
    body = "\n".join(
        [
            "- [ ] #30: closed but never ticked",
            "- [x] #31: ticked while still open",
            "- [x] #32: ticked and closed",
            "- [ ] #33: open and unticked",
            "- [ ] #99: listed but never linked as a sub-issue",
            "Prose mentioning #30 is not a box.",
        ]
    )
    wmap = module.WayfinderMap.from_issue(
        _issue(_node(30, state="CLOSED"), _node(31), _node(32, state="CLOSED"), _node(33), body=body)
    )

    assert module.checklist_drift(wmap) == [
        "#30 is closed but unticked",
        "#31 is ticked but open",
        "#99 is in the checklist but not a sub-issue",
    ]


def test_main_reports_each_named_map_from_its_graphql_answer(monkeypatch, capsys):
    module = _frontier_module()
    answers = {
        "1": _issue(_node(40), body="- [ ] #40: next"),
        "2": {"number": 2, "title": "Empty map", "body": None, "subIssues": {"nodes": []}},
    }

    def fake_gh(*args):
        number = next(arg.removeprefix("number=") for arg in args if arg.startswith("number="))
        return json.dumps({"data": {"repository": {"issue": answers[number]}}})

    monkeypatch.setattr(module, "_gh", fake_gh)

    assert module.main(["wayfinder_frontier.py", "1", "#2"]) == 0
    out = capsys.readouterr().out
    assert "  frontier: #40 Child 40" in out
    assert "#2 Empty map\n  no sub-issues: link each child as a sub-issue of the map" in out


def test_a_non_numeric_map_argument_is_a_usage_error(capsys):
    module = _frontier_module()

    assert module.main(["wayfinder_frontier.py", "abc"]) == 2
    assert "usage:" in capsys.readouterr().err

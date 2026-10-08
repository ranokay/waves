"""The frontier report names the issue an agent may take next.

`mise run frontier` replaces a per-issue `gh issue view` sweep: the first
open, unassigned, `ready-for-agent` child with every blocker closed is the
frontier, a map with none ready names what it waits on, and checklist boxes
that disagree with the tracker are listed for the delivering run to correct.
These drive the report on hand-built GraphQL nodes; no network.
"""

from __future__ import annotations

import importlib.util
import sys

from support.paths import REPO_ROOT


def _frontier_module():
    spec = importlib.util.spec_from_file_location("frontier", REPO_ROOT / "tools" / "frontier.py")
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


def _children(module, *nodes):
    return [module.Child.from_node(node) for node in nodes]


def test_the_first_ready_child_in_map_order_is_the_frontier():
    module = _frontier_module()
    children = _children(
        module,
        _node(10, state="CLOSED"),
        _node(11, blockers=[(10, "CLOSED")]),
        _node(12),
    )

    lines = module.report(1, "Map", "", children)

    assert "  frontier: #11 Child 11" in lines
    assert "  also ready: #12 Child 12" in lines


def test_a_map_with_nothing_ready_names_what_it_waits_on():
    module = _frontier_module()
    children = _children(
        module,
        _node(20, assignees=["ranokay"], labels=["ready-for-human"]),
        _node(21, blockers=[(20, "OPEN")]),
        _node(22, assignees=["someone"]),
        _node(23, labels=["needs-triage"]),
    )

    lines = module.report(1, "Map", "", children)

    assert "  frontier: none ready for an agent" in lines
    assert "    #20 needs a human (ranokay): Child 20" in lines
    assert "    #22 claimed (someone): Child 22" in lines
    assert "    #23 not labelled ready-for-agent: Child 23" in lines
    assert "    #21 blocked by #20: Child 21" in lines


def test_checklist_boxes_that_disagree_with_the_tracker_are_reported():
    module = _frontier_module()
    children = _children(module, _node(30, state="CLOSED"), _node(31), _node(32, state="CLOSED"), _node(33))
    body = "\n".join(
        [
            "- [ ] #30: closed but never ticked",
            "- [x] #31: ticked while still open",
            "- [x] #32: ticked and closed",
            "- [ ] #33: open and unticked",
            "- [ ] #99: not a child of this map",
            "Prose mentioning #30 is not a box.",
        ]
    )

    assert module.checklist_drift(body, children) == ["#30 is closed but unticked", "#31 is ticked but open"]


def test_a_non_numeric_map_argument_is_a_usage_error(capsys):
    module = _frontier_module()

    assert module.main(["frontier.py", "abc"]) == 2
    assert "usage:" in capsys.readouterr().err

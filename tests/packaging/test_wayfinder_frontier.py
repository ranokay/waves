"""The frontier report names the issue an agent may take next.

`mise run frontier` replaces a per-issue `gh issue view` sweep: the first
open, unassigned `ready-for-agent` child with every blocker closed is the
frontier, a map with none ready names what it waits on, and checklist entries
that disagree with the tracker are listed for the delivering run to correct.
Readiness declarations distinguish the selected slice from completion inputs;
undeclared readiness requires preflight and pending slice inputs prevent selection.
These drive the report on hand-built GraphQL payloads, with `gh` faked; no
network.
"""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest
from support.paths import REPO_ROOT


def _frontier_module():
    spec = importlib.util.spec_from_file_location("wayfinder_frontier", REPO_ROOT / "tools" / "wayfinder_frontier.py")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve the module's annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _node(number, *, state="OPEN", assignees=(), labels=("ready-for-agent",), blockers=(), body=""):
    return {
        "number": number,
        "title": f"Child {number}",
        "body": body,
        "state": state,
        "assignees": {"nodes": [{"login": login} for login in assignees]},
        "labels": {"nodes": [{"name": name} for name in labels]},
        "blockedBy": {"nodes": [{"number": n, "state": s} for n, s in blockers]},
    }


def _issue(*nodes, body=""):
    return {"number": 1, "title": "Map", "body": body, "subIssues": {"nodes": list(nodes)}}


def _report(module, *nodes, body=""):
    return module.report(module.WayfinderMap.from_issue(_issue(*nodes, body=body)))


def _readiness(*, slice_inputs="- None.", completion_inputs="- None."):
    return f"""## Agent readiness

- Selected slice: Implement the runtime registry with synthetic fixtures.
- Acceptance condition: Registry behavior tests pass without claiming native qualification.

### Slice inputs

{slice_inputs}

### Completion inputs

{completion_inputs}
"""


def test_the_first_ready_child_in_map_order_is_the_frontier():
    module = _frontier_module()

    lines = _report(module, _node(10, state="CLOSED"), _node(11, blockers=[(10, "CLOSED")]), _node(12))

    assert "  frontier: #11 Child 11" in lines
    assert "  also ready: #12 Child 12" in lines


def test_legacy_readiness_is_unknown_even_after_native_blockers_close():
    module = _frontier_module()

    lines = _report(module, _node(11, blockers=[(10, "CLOSED")]))

    assert "  frontier: #11 Child 11" in lines
    assert "    readiness: unknown; needs preflight (missing or malformed Agent readiness)" in lines
    assert not any("declared available" in line for line in lines)


def test_completion_inputs_do_not_block_a_declared_implementation_slice():
    module = _frontier_module()
    body = _readiness(
        slice_inputs="- [x] Synthetic runtime fixtures",
        completion_inputs="- [ ] Windows host for native qualification\n- [ ] Approved runtime artifact",
    )

    lines = _report(module, _node(11, body=body))

    assert "  frontier: #11 Child 11" in lines
    assert "    selected slice: Implement the runtime registry with synthetic fixtures." in lines
    assert "    acceptance condition: Registry behavior tests pass without claiming native qualification." in lines
    assert "    slice inputs: declared available or none required" in lines
    assert "    completion inputs: pending: Windows host for native qualification; Approved runtime artifact" in lines


def test_a_pending_slice_input_is_reported_and_skipped_in_map_order():
    module = _frontier_module()
    body = _readiness(slice_inputs="- [ ] Approved runtime artifact")

    lines = _report(module, _node(11, body=body), _node(12, body=_readiness()))

    assert "  frontier: #12 Child 12" in lines
    assert "  unblocked but not ready:" in lines
    assert "    #11 slice inputs pending: Approved runtime artifact: Child 11" in lines
    assert not any("frontier: #11" in line or "also ready: #11" in line for line in lines)


def test_a_map_waiting_only_on_slice_inputs_reports_no_frontier():
    module = _frontier_module()

    lines = _report(module, _node(11, body=_readiness(slice_inputs="- [ ] Qualification host")))

    assert "  frontier: none ready for an agent" in lines
    assert "    #11 slice inputs pending: Qualification host: Child 11" in lines


@pytest.mark.parametrize(
    "body",
    [
        "## Agent readiness\n- Selected slice: Implement the registry.",
        _readiness().replace("- Acceptance condition:", "- Acceptance:"),
        _readiness(slice_inputs="- None.\n- [x] Synthetic fixtures"),
        _readiness(completion_inputs="- pending host"),
        _readiness() + _readiness(),
        "```markdown\n" + _readiness() + "```",
    ],
    ids=["incomplete", "wrong-field", "mixed-none", "invalid-input", "duplicate", "fenced-example"],
)
def test_malformed_readiness_keeps_legacy_selection_with_explicit_preflight(body):
    module = _frontier_module()

    lines = _report(module, _node(11, body=body))

    assert "  frontier: #11 Child 11" in lines
    assert "    readiness: unknown; needs preflight (missing or malformed Agent readiness)" in lines
    assert not any("declared available" in line for line in lines)


def test_a_shorter_backtick_fence_keeps_nested_readiness_examples_out_of_selection():
    module = _frontier_module()
    example = _readiness(slice_inputs="- [ ] Example artifact")
    body = "````markdown\n```markdown\n" + example + "```\n````\n" + _readiness()

    lines = _report(module, _node(11, body=body))

    assert "  frontier: #11 Child 11" in lines
    assert "    selected slice: Implement the runtime registry with synthetic fixtures." in lines
    assert not any("Example artifact" in line or "readiness: unknown" in line for line in lines)


@pytest.mark.parametrize("inner_line", ["~~~", "````", "~~~~ trailing text"])
def test_a_tilde_fence_closes_only_on_a_long_enough_matching_run_without_text(inner_line):
    module = _frontier_module()
    example = _readiness(slice_inputs="- [ ] Example artifact")
    body = "~~~~markdown\n" + inner_line + "\n" + example + "~~~~~   \n" + _readiness()

    lines = _report(module, _node(11, body=body))

    assert "  frontier: #11 Child 11" in lines
    assert "    selected slice: Implement the runtime registry with synthetic fixtures." in lines
    assert not any("Example artifact" in line or "readiness: unknown" in line for line in lines)


@pytest.mark.parametrize("indentation", ["    ", "\t"])
@pytest.mark.parametrize("fenced", [False, True], ids=["plain-code", "fenced-code"])
def test_indented_code_examples_do_not_add_readiness_requirements(indentation, fenced):
    module = _frontier_module()
    example = _readiness(slice_inputs="- [ ] Example artifact")
    if fenced:
        example = "```markdown\n" + example + "```\n"
    body = "\n".join(indentation + line for line in example.splitlines()) + "\n\n" + _readiness()

    lines = _report(module, _node(11, body=body))

    assert "  frontier: #11 Child 11" in lines
    assert "    selected slice: Implement the runtime registry with synthetic fixtures." in lines
    assert not any("Example artifact" in line or "readiness: unknown" in line for line in lines)


@pytest.mark.parametrize("indentation", ["    ", "\t"])
def test_a_pending_nested_input_is_not_discarded_as_an_indented_code_example(indentation):
    module = _frontier_module()
    body = _readiness(slice_inputs=f"- [x] Runtime downloaded\n{indentation}- [ ] License grant for runtime use")

    lines = _report(module, _node(11, body=body), _node(12, body=_readiness()))

    assert "  frontier: #12 Child 12" in lines
    assert any("#11 slice inputs pending: License grant for runtime use" in line for line in lines)
    assert any("readiness: unknown; needs preflight" in line for line in lines)


def test_a_deeper_pending_nested_input_remains_a_holdup():
    module = _frontier_module()
    body = _readiness(slice_inputs="- [x] Runtime downloaded\n    - [x] Account selected\n        - [ ] License grant")

    lines = _report(module, _node(11, body=body))

    assert "  frontier: none ready for an agent" in lines
    assert any("slice inputs pending: License grant" in line for line in lines)


def test_indented_code_beneath_a_list_item_does_not_become_a_pending_input():
    module = _frontier_module()
    body = _readiness(slice_inputs="- [x] Runtime downloaded\n\n        - [ ] Example only")

    lines = _report(module, _node(11, body=body))

    assert "  frontier: #11 Child 11" in lines
    assert not any("Example only" in line or "readiness: unknown" in line for line in lines)


def test_a_pending_slice_input_still_blocks_an_incomplete_declaration():
    module = _frontier_module()
    body = "## Agent readiness\n### Slice inputs\n- [ ] Approved artifact"

    lines = _report(module, _node(11, body=body), _node(12))

    assert "  frontier: #12 Child 12" in lines
    assert "    #11 slice inputs pending: Approved artifact: Child 11" in lines
    assert "      readiness: unknown; needs preflight (missing or malformed Agent readiness)" in lines


def test_readiness_declarations_keep_human_assignee_and_native_blocker_gates():
    module = _frontier_module()
    body = _readiness()

    lines = _report(
        module,
        _node(20, body=body, labels=["ready-for-agent", "ready-for-human"]),
        _node(21, body=body, assignees=["someone"]),
        _node(22, body=body, blockers=[(19, "OPEN")]),
        _node(23, body=body, labels=["needs-triage"]),
    )

    assert "  frontier: none ready for an agent" in lines
    assert "    #20 needs a human: Child 20" in lines
    assert "    #21 claimed (someone): Child 21" in lines
    assert "    #22 blocked by #19: Child 22" in lines
    assert "    #23 not labelled ready-for-agent: Child 23" in lines


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


def test_checklist_entries_that_disagree_with_the_tracker_are_reported_once():
    module = _frontier_module()
    body = "\n".join(
        [
            "- [ ] #30: closed but never ticked",
            "- [x] #31: ticked while still open",
            "- [x] #32: ticked and closed",
            "- [ ] #33: open and unticked",
            "- [ ] #99: listed but never linked as a sub-issue",
            "- [ ] #99: listed twice",
            "Prose mentioning #34 is not a box.",
        ]
    )

    lines = _report(
        module, _node(30, state="CLOSED"), _node(31), _node(32, state="CLOSED"), _node(33), _node(34), body=body
    )

    drift = lines[lines.index("  checklist drift:") + 1 :]
    assert drift == [
        "    #30 is closed but unticked",
        "    #31 is ticked but open",
        "    #99 is in the checklist but not a sub-issue",
        "    #34 is a sub-issue but not in the checklist",
    ]


def _fake_gh(answers, open_maps=(), calls=None):
    def fake_gh(*args):
        if calls is not None:
            calls.append(args)
        if args[0] == "issue":
            return json.dumps([{"number": n} for n in open_maps])
        number = next(arg.removeprefix("number=") for arg in args if arg.startswith("number="))
        return json.dumps({"data": {"repository": {"issue": answers.get(number)}}})

    return fake_gh


def test_main_prints_a_report_for_each_named_map(monkeypatch, capsys):
    module = _frontier_module()
    answers = {
        "1": _issue(_node(40), body="- [ ] #40: next"),
        "2": {"number": 2, "title": "Empty map", "body": "- [ ] #41: listed only", "subIssues": {"nodes": []}},
    }
    monkeypatch.setattr(module, "_gh", _fake_gh(answers))

    assert module.main(["wayfinder_frontier.py", "1", "#2"]) == 0
    out = capsys.readouterr().out
    assert "  frontier: #40 Child 40" in out
    assert "#2 Empty map\n  no sub-issues: link each child as a sub-issue of the map" in out
    assert "    #41 is in the checklist but not a sub-issue" in out


def test_main_fetches_child_readiness_in_the_same_graphql_call(monkeypatch, capsys):
    module = _frontier_module()
    calls: list = []
    monkeypatch.setattr(module, "_gh", _fake_gh({"1": _issue(_node(40, body=_readiness()))}, calls=calls))

    assert module.main(["wayfinder_frontier.py", "1"]) == 0

    assert "selected slice: Implement the runtime registry with synthetic fixtures." in capsys.readouterr().out
    assert len(calls) == 1
    assert calls[0][:2] == ("api", "graphql")
    query = next(arg for arg in calls[0] if arg.startswith("query="))
    child_selection = query.split("subIssues(first: 100)", 1)[1]
    assert "number title body state" in child_selection


def test_main_without_arguments_reports_every_open_map(monkeypatch, capsys):
    module = _frontier_module()
    calls: list = []
    monkeypatch.setattr(module, "_gh", _fake_gh({"7": _issue(_node(50))}, open_maps=[7], calls=calls))

    assert module.main(["wayfinder_frontier.py"]) == 0
    assert "  frontier: #50 Child 50" in capsys.readouterr().out
    listing = next(call for call in calls if call[0] == "issue")
    assert int(listing[listing.index("--limit") + 1]) > 30, "gh lists only 30 maps by default"


def test_an_unknown_map_fails_after_the_reports_already_printed(monkeypatch, capsys):
    module = _frontier_module()
    monkeypatch.setattr(module, "_gh", _fake_gh({"1": _issue(_node(60))}))

    with pytest.raises(SystemExit) as exit_info:
        module.main(["wayfinder_frontier.py", "1", "9999"])

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "  frontier: #60 Child 60" in captured.out
    assert "#9999 not found" in captured.err


def test_a_non_numeric_map_argument_is_a_usage_error(capsys):
    module = _frontier_module()

    assert module.main(["wayfinder_frontier.py", "abc"]) == 2
    assert "usage:" in capsys.readouterr().err

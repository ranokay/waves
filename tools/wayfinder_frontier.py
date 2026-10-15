#!/usr/bin/env python
"""Report a wayfinder map's frontier: the next issue an agent may take.

A map is an open issue labelled `wayfinder:map` whose children are GitHub
sub-issues, each also listed in the map body's checklist
(docs/agents/issue-tracker.md). One GraphQL call per map returns every child
with its body, live state, assignees, labels and native blockers. A child is ready
for an agent when it is open, labelled `ready-for-agent` (and not
`ready-for-human`), unassigned, and every issue blocking it is closed; the
first ready child in map order is the frontier. A declared pending input for
the selected slice also holds a child back. Missing or malformed readiness
declarations keep the existing selection rules but require preflight; closed
blockers do not establish qualification or external-input availability.
When nothing is ready, the
open children that nothing blocks name what the map waits on. The report ends
with checklist entries that disagree with the tracker: a tick against the
live state, a checklist child that is not linked as a sub-issue (and so
reaches no other part of the report), or a sub-issue with no checklist row.

Usage: wayfinder_frontier.py [MAP ...]    (no argument reports every open map)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import NoReturn

REPO = os.environ.get("GH_REPO", "ranokay/waves")
MAP_LABEL = "wayfinder:map"
AGENT_LABEL = "ready-for-agent"
HUMAN_LABEL = "ready-for-human"

# GitHub's own ceilings: 100 sub-issues per parent, 50 blocked-by edges per
# issue, 10 assignees, 100 labels; so every connection below reads in full.
MAP_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number title body
      subIssues(first: 100) {
        nodes {
          number title body state
          assignees(first: 10) { nodes { login } }
          labels(first: 100) { nodes { name } }
          blockedBy(first: 50) { nodes { number state } }
        }
      }
    }
  }
}
"""

# A checklist line names its child first: "- [x] #580: Ratify ...".
CHECKBOX = re.compile(r"^\s*[-*] \[([ xX])\] #(\d+)\b", re.MULTILINE)
READINESS = re.compile(
    r"- Selected slice: (?P<slice>[^\n]+)\n"
    r"- Acceptance condition: (?P<acceptance>[^\n]+)\n"
    r"### Slice inputs\n(?P<slice_inputs>.*?)\n"
    r"### Completion inputs\n(?P<completion_inputs>.+)",
    re.DOTALL,
)
INPUT_ITEM = re.compile(r"- \[([ xX])\] (\S.*)")
SLICE_INPUTS = re.compile(r"(?:\A|\n)### Slice inputs\n(.*?)(?=\n#+ |\Z)", re.DOTALL)


def readiness_sections(body: str) -> list[str]:
    """Read declarations outside fenced examples, ending at the next peer heading."""
    sections: list[list[str]] = []
    current: list[str] | None = None
    fence = ""
    for raw_line in body.splitlines():
        line = raw_line.strip()
        marker = line[:3]
        if marker in ("```", "~~~") and (not fence or marker == fence):
            fence = "" if fence else marker
            continue
        if fence:
            continue
        if line == "## Agent readiness":
            current = []
            sections.append(current)
        elif re.match(r"^#{1,2}(?:\s|$)", line):
            current = None
        elif current is not None and line:
            current.append(line)
    return ["\n".join(section) for section in sections]


def input_requirements(block: str) -> tuple[tuple[str, ...], bool]:
    """Return declared pending inputs and whether every entry uses the contract."""
    if block == "- None.":
        return (), True
    items = [INPUT_ITEM.fullmatch(line) for line in block.splitlines()]
    pending = tuple(item[2] for item in items if item and item[1] == " ")
    return pending, bool(items) and all(items)


@dataclass(frozen=True)
class AgentReadiness:
    selected_slice: str = ""
    acceptance: str = ""
    pending_slice_inputs: tuple[str, ...] = ()
    pending_completion_inputs: tuple[str, ...] = ()
    valid: bool = False

    @classmethod
    def from_body(cls, body: str) -> AgentReadiness:
        sections = readiness_sections(body)
        # A partial or duplicate declaration can still name a required pending
        # input. Preserve that holdup even though the declaration needs preflight.
        pending_slice = tuple(
            item
            for section in sections
            for block in SLICE_INPUTS.findall(section)
            for item in input_requirements(block)[0]
        )
        match = READINESS.fullmatch(sections[0]) if len(sections) == 1 else None
        if match is None:
            return cls(pending_slice_inputs=pending_slice)
        _, slice_valid = input_requirements(match["slice_inputs"])
        pending_completion, completion_valid = input_requirements(match["completion_inputs"])
        return cls(
            selected_slice=match["slice"],
            acceptance=match["acceptance"],
            pending_slice_inputs=pending_slice,
            pending_completion_inputs=pending_completion,
            valid=slice_valid and completion_valid,
        )

    def report_lines(self) -> list[str]:
        if not self.valid:
            return ["    readiness: unknown; needs preflight (missing or malformed Agent readiness)"]
        completion = (
            "pending: " + "; ".join(self.pending_completion_inputs)
            if self.pending_completion_inputs
            else "no declared pending inputs"
        )
        return [
            f"    selected slice: {self.selected_slice}",
            f"    acceptance condition: {self.acceptance}",
            "    slice inputs: declared available or none required",
            f"    completion inputs: {completion}",
        ]


@dataclass(frozen=True)
class Child:
    number: int
    title: str
    open: bool
    assignees: tuple[str, ...]
    labels: frozenset[str]
    open_blockers: tuple[int, ...]
    readiness: AgentReadiness

    @classmethod
    def from_node(cls, node: dict) -> Child:
        return cls(
            number=node["number"],
            title=node["title"],
            open=node["state"] == "OPEN",
            assignees=tuple(a["login"] for a in node["assignees"]["nodes"]),
            labels=frozenset(label["name"] for label in node["labels"]["nodes"]),
            open_blockers=tuple(b["number"] for b in node["blockedBy"]["nodes"] if b["state"] == "OPEN"),
            readiness=AgentReadiness.from_body(node.get("body") or ""),
        )

    def holdup(self) -> str | None:
        """Why an open child is not ready for an agent, or None when it is."""
        if self.open_blockers:
            return "blocked by " + ", ".join(f"#{n}" for n in self.open_blockers)
        owner = f" ({', '.join(self.assignees)})" if self.assignees else ""
        if HUMAN_LABEL in self.labels:
            return f"needs a human{owner}"
        if self.assignees:
            return f"claimed{owner}"
        if AGENT_LABEL not in self.labels:
            return f"not labelled {AGENT_LABEL}"
        if self.readiness.pending_slice_inputs:
            return "slice inputs pending: " + "; ".join(self.readiness.pending_slice_inputs)
        return None

    @property
    def ready(self) -> bool:
        return self.open and self.holdup() is None

    def report_line(self) -> str:
        """An open, not-ready child as the report lists it."""
        return f"    #{self.number} {self.holdup()}: {self.title}"


@dataclass(frozen=True)
class WayfinderMap:
    number: int
    title: str
    body: str
    children: tuple[Child, ...]

    @classmethod
    def from_issue(cls, issue: dict) -> WayfinderMap:
        return cls(
            number=issue["number"],
            title=issue["title"],
            body=issue["body"] or "",
            children=tuple(Child.from_node(node) for node in issue["subIssues"]["nodes"]),
        )


def checklist_drift(wmap: WayfinderMap) -> list[str]:
    """Checklist entries that disagree with the tracker."""
    by_number = {child.number: child for child in wmap.children}
    drift: list[str] = []
    listed: set[int] = set()
    for mark, number in CHECKBOX.findall(wmap.body):
        listed.add(int(number))
        child = by_number.get(int(number))
        if child is None:
            drift.append(f"#{number} is in the checklist but not a sub-issue")
            continue
        ticked = mark != " "
        if ticked and child.open:
            drift.append(f"#{child.number} is ticked but open")
        elif not ticked and not child.open:
            drift.append(f"#{child.number} is closed but unticked")
    drift += [
        f"#{child.number} is a sub-issue but not in the checklist"
        for child in wmap.children
        if child.number not in listed
    ]
    # A child listed twice reports once.
    return list(dict.fromkeys(drift))


def frontier_lines(children: tuple[Child, ...]) -> list[str]:
    """The frontier, or what the map waits on, then the blocked children."""
    open_children = [child for child in children if child.open]
    lines = [f"  {len(open_children)} open, {len(children) - len(open_children)} closed"]
    ready = [child for child in open_children if child.ready]
    if ready:
        for index, child in enumerate(ready):
            prefix = "frontier" if index == 0 else "also ready"
            lines.append(f"  {prefix}: #{child.number} {child.title}")
            lines.extend(child.readiness.report_lines())
    else:
        lines.append("  frontier: none ready for an agent")
    unblocked = [
        child
        for child in open_children
        if not child.open_blockers and (not ready or child.readiness.pending_slice_inputs)
    ]
    if unblocked:
        lines.append("  unblocked but not ready:")
        for child in unblocked:
            lines.append(child.report_line())
            if child.readiness.pending_slice_inputs and not child.readiness.valid:
                lines.extend("  " + line for line in child.readiness.report_lines())
    blocked = [child for child in open_children if child.open_blockers]
    if blocked:
        lines.append("  blocked:")
        lines.extend(child.report_line() for child in blocked)
    return lines


def report(wmap: WayfinderMap) -> list[str]:
    lines = [f"#{wmap.number} {wmap.title}"]
    if wmap.children:
        lines.extend(frontier_lines(wmap.children))
    else:
        lines.append("  no sub-issues: link each child as a sub-issue of the map")
    drift = checklist_drift(wmap)
    if drift:
        lines.append("  checklist drift:")
        lines.extend(f"    {entry}" for entry in drift)
    return lines


def _fail(message: str) -> NoReturn:
    print(f"frontier: {message}", file=sys.stderr)
    raise SystemExit(1)


def _gh(*args: str) -> str:
    gh = shutil.which("gh")
    if gh is None:
        _fail("the GitHub CLI (gh) is not on PATH")
    result = subprocess.run([gh, *args], check=False, capture_output=True, text=True)  # noqa: S603 (fixed argv: gh plus this script's own arguments)
    if result.returncode != 0:
        _fail(f"gh {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def _open_maps() -> list[int]:
    # gh lists 30 issues unless told otherwise; ask for more maps than a repo holds.
    out = _gh(
        "issue", "list", "--repo", REPO, "--label", MAP_LABEL, "--state", "open", "--limit", "1000", "--json", "number"
    )
    return sorted(entry["number"] for entry in json.loads(out))


def _fetch_map(number: int) -> WayfinderMap:
    owner, name = REPO.split("/", 1)
    out = _gh(
        "api",
        "graphql",
        "-f",
        f"query={MAP_QUERY}",
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-F",
        f"number={number}",
    )
    issue = json.loads(out)["data"]["repository"]["issue"]
    if issue is None:
        _fail(f"#{number} not found in {REPO}")
    return WayfinderMap.from_issue(issue)


def main(argv: list[str]) -> int:
    try:
        maps = [int(arg.lstrip("#")) for arg in argv[1:]] or _open_maps()
    except ValueError:
        print(f"usage: {argv[0]} [MAP ...]", file=sys.stderr)
        return 2
    if not maps:
        print(f"frontier: no open {MAP_LABEL} issue in {REPO}")
        return 0
    for index, number in enumerate(maps):
        # Each report prints before the next fetch, so a failing map keeps
        # the reports already printed.
        print(("\n" if index else "") + "\n".join(report(_fetch_map(number))), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

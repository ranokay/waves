#!/usr/bin/env python
"""Report a wayfinder map's frontier: the next issue an agent may take.

A map is an open issue labelled `wayfinder:map` whose children are GitHub
sub-issues (docs/agents/issue-tracker.md). One GraphQL call per map returns
every child with its live state, assignees, labels and blockers. A child is
ready for an agent when it is open, labelled `ready-for-agent`, unassigned,
and every issue blocking it is closed; the first ready child in map order is
the frontier. When nothing is ready, the open children that nothing blocks
name what the roadmap waits on. The report ends with the map's checklist
boxes that disagree with the tracker, for the delivering run to correct.

Usage: frontier.py [MAP ...]    (no argument reports every open map)
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

MAP_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number title state body
      subIssues(first: 100) {
        nodes {
          number title state
          assignees(first: 10) { nodes { login } }
          labels(first: 20) { nodes { name } }
          blockedBy(first: 50) { nodes { number state } }
        }
      }
    }
  }
}
"""

# A checklist line names its child first: "- [x] #580: Ratify ...".
CHECKBOX = re.compile(r"^\s*[-*] \[([ xX])\] #(\d+)\b", re.MULTILINE)


@dataclass(frozen=True)
class Child:
    number: int
    title: str
    open: bool
    assignees: tuple[str, ...]
    labels: frozenset[str]
    open_blockers: tuple[int, ...]

    @classmethod
    def from_node(cls, node: dict) -> Child:
        return cls(
            number=node["number"],
            title=node["title"],
            open=node["state"] == "OPEN",
            assignees=tuple(a["login"] for a in node["assignees"]["nodes"]),
            labels=frozenset(label["name"] for label in node["labels"]["nodes"]),
            open_blockers=tuple(b["number"] for b in node["blockedBy"]["nodes"] if b["state"] == "OPEN"),
        )

    @property
    def ready(self) -> bool:
        return self.open and not self.open_blockers and not self.assignees and AGENT_LABEL in self.labels

    def reason(self) -> str:
        """Why an open child is not ready, in the order an agent acts on it."""
        if self.open_blockers:
            return "blocked by " + ", ".join(f"#{n}" for n in self.open_blockers)
        owner = f" ({', '.join(self.assignees)})" if self.assignees else ""
        if HUMAN_LABEL in self.labels:
            return f"needs a human{owner}"
        if self.assignees:
            return f"claimed{owner}"
        if AGENT_LABEL not in self.labels:
            return f"not labelled {AGENT_LABEL}"
        return "ready"


def checklist_drift(body: str, children: list[Child]) -> list[str]:
    """Checklist boxes whose tick disagrees with the child's live state."""
    by_number = {child.number: child for child in children}
    drift = []
    for mark, number in CHECKBOX.findall(body or ""):
        child = by_number.get(int(number))
        if child is None:
            continue
        ticked = mark != " "
        if ticked and child.open:
            drift.append(f"#{child.number} is ticked but open")
        elif not ticked and not child.open:
            drift.append(f"#{child.number} is closed but unticked")
    return drift


def report(number: int, title: str, body: str, children: list[Child]) -> list[str]:
    open_children = [child for child in children if child.open]
    lines = [f"#{number} {title}", f"  {len(open_children)} open, {len(children) - len(open_children)} closed"]
    ready = [child for child in open_children if child.ready]
    if ready:
        lines.append(f"  frontier: #{ready[0].number} {ready[0].title}")
        lines.extend(f"  also ready: #{child.number} {child.title}" for child in ready[1:])
    else:
        lines.append("  frontier: none ready for an agent")
        unblocked = [child for child in open_children if not child.open_blockers]
        if unblocked:
            lines.append("  unblocked but not ready:")
            lines.extend(f"    #{child.number} {child.reason()}: {child.title}" for child in unblocked)
    blocked = [child for child in open_children if child.open_blockers]
    if blocked:
        lines.append("  blocked:")
        lines.extend(f"    #{child.number} {child.reason()}: {child.title}" for child in blocked)
    drift = checklist_drift(body, children)
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
    out = _gh("issue", "list", "--repo", REPO, "--label", MAP_LABEL, "--state", "open", "--json", "number")
    return sorted(entry["number"] for entry in json.loads(out))


def _fetch_map(number: int) -> tuple[str, str, list[Child]]:
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
    children = [Child.from_node(node) for node in issue["subIssues"]["nodes"]]
    return issue["title"], issue["body"], children


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
        title, body, children = _fetch_map(number)
        if index:
            print()
        if not children:
            print(f"#{number} {title}\n  no sub-issues: link the children as sub-issues of the map")
            continue
        print("\n".join(report(number, title, body, children)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

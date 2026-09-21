"""The repository's decision records and glossary stay complete.

WHAT THIS FENCES OFF
--------------------
The onboarding, My Music and provider-surface decisions are recorded as ADRs,
and the vocabulary they rest on (Onboarding, Saved vs Library, My Music) is
defined in the glossary. The guard is mechanical: an ADR missing its status,
its decision, its reasoning or its consequences, or a glossary that lost one
of the shared terms, fails here instead of surfacing in a later review.

Three markers are mandatory for every record (Status/Decided headers plus
Decision/Why/Consequences sections); the onboarding decision records are
additionally held to the "Alternatives considered" section the onboarding spec
asked for.

The R-02 disposition table is held the same way: every open P1/P2 review
thread the audit found must appear there exactly once, each with a verdict
and a current-path citation, so a dropped row fails here instead of
silently reopening the finding.
"""

from __future__ import annotations

import re
from pathlib import Path

from support.paths import REPO_ROOT

ADR_DIR = REPO_ROOT / "docs" / "adr"
CONTEXT = REPO_ROOT / "CONTEXT.md"
DISPOSITIONS = REPO_ROOT / "docs" / "review-thread-dispositions.md"

# The three settled decisions the onboarding spec asked to record.
DECISION_SLUGS = (
    "onboarding-state-machine",
    "my-music-information-architecture",
    "capability-driven-provider-surfaces",
)

GLOSSARY_TERMS = ("**Onboarding**", "**My Music**", "**Saved vs Library**")

_MANDATORY = ("- Status:", "- Decided:", "## Decision", "## Why", "## Consequences")


def _adrs() -> list[Path]:
    files = sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert files, f"no decision records found under {ADR_DIR}"
    return files


def test_every_decision_record_states_its_status_and_decision():
    for path in _adrs():
        text = path.read_text(encoding="utf-8")
        for marker in _MANDATORY:
            assert marker in text, f"{path.name} is missing {marker!r}"


def test_the_settled_onboarding_decisions_are_recorded():
    for slug in DECISION_SLUGS:
        hits = sorted(ADR_DIR.glob(f"*-{slug}.md"))
        assert len(hits) == 1, f"expected one decision record for {slug!r}, found {hits}"
        text = hits[0].read_text(encoding="utf-8")
        assert "## Alternatives considered" in text, f"{hits[0].name} is missing its alternatives"


def test_the_glossary_defines_the_shared_terms():
    text = CONTEXT.read_text(encoding="utf-8")

    for term in GLOSSARY_TERMS:
        assert term in text, f"CONTEXT.md does not define {term!r}"


# The 98 open P1/P2 discussion ids the audit captured (HD-04: 33 P1 + 65 P2
# across PRs 37, 44-48, 51, 56, 57). Thread ids are stable, so this set does
# not move when a deferred row later lands — only the row's verdict changes.
DISPOSITION_THREAD_IDS = (
    "r3910736930",
    "r3910736935",
    "r3953672477",
    "r3953672481",
    "r3953672484",
    "r3953808040",
    "r3953842699",
    "r3953874168",
    "r3953874171",
    "r3953917560",
    "r3954270556",
    "r3954270560",
    "r3954270564",
    "r3954270567",
    "r3954340351",
    "r3954340359",
    "r3954340364",
    "r3954340368",
    "r3954380373",
    "r3954380378",
    "r3954380383",
    "r3954380387",
    "r3954431703",
    "r3954431707",
    "r3954431709",
    "r3954489964",
    "r3954489970",
    "r3954489973",
    "r3954821773",
    "r3954821776",
    "r3954821780",
    "r3954821782",
    "r3961848059",
    "r3961848065",
    "r3961848076",
    "r3961848086",
    "r3961959298",
    "r3962050519",
    "r3962050528",
    "r3962050537",
    "r3962050542",
    "r3962180503",
    "r3962180510",
    "r3962180513",
    "r3962287135",
    "r3962407388",
    "r3962407397",
    "r3962539240",
    "r3962539249",
    "r3962539254",
    "r3962592789",
    "r3962592794",
    "r3962592801",
    "r3962592806",
    "r3962661472",
    "r3962661478",
    "r3962785723",
    "r3962785729",
    "r3962877823",
    "r3962877833",
    "r3962877839",
    "r3962877844",
    "r3963933125",
    "r3963933132",
    "r3963933136",
    "r3963933139",
    "r3963933144",
    "r3964074448",
    "r3964074451",
    "r3964074452",
    "r3964074456",
    "r3964074458",
    "r3964219497",
    "r3964219500",
    "r3964219502",
    "r3964219504",
    "r3965893583",
    "r3966143683",
    "r3966143687",
    "r3966143692",
    "r3966463155",
    "r3966463161",
    "r3966569063",
    "r3966569071",
    "r3966569078",
    "r3966569087",
    "r3966697718",
    "r3966697727",
    "r3966765847",
    "r3966836787",
    "r3966928090",
    "r3967008092",
    "r3967099651",
    "r3967099658",
    "r3967253122",
    "r3967253139",
    "r3967390200",
    "r3967390207",
)

_VERDICTS = ("fixed-in", "refuted", "deferred")


def test_every_open_p1_p2_thread_has_a_disposition():
    text = DISPOSITIONS.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if "discussion_" in line]
    found = re.findall(r"discussion_(r\d+)", text)
    assert sorted(found) == sorted(DISPOSITION_THREAD_IDS), (
        f"the table covers {len(set(found))} threads, expected {len(DISPOSITION_THREAD_IDS)}"
    )
    assert len(rows) == len(found), "a thread id appears outside a table row"
    for row in rows:
        # Cell-scoped: the verdict belongs in the Disposition cell and the
        # citation in the Evidence cell, so prose mentioning a verdict
        # elsewhere cannot satisfy the contract.
        cells = [cell.strip() for cell in row.split("|")]
        assert len(cells) == 7, f"malformed row: {row[:120]}"
        assert any(verdict in cells[4] for verdict in _VERDICTS), f"no verdict: {row[:120]}"
        assert re.search(r"waves/[^`]*:\d+", cells[5]), f"no current-path citation: {row[:120]}"

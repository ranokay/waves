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
"""

from __future__ import annotations

from pathlib import Path

from support.paths import REPO_ROOT

ADR_DIR = REPO_ROOT / "docs" / "adr"
CONTEXT = REPO_ROOT / "CONTEXT.md"

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

"""Adaptive learning pathway.

A `Pathway` is the ordered sequence of concepts Stuart plans to lead the
student through for a given session or stretch of sessions. It is a
plan, not a rigid track — the engagement loop can insert re-teach
blocks, skip ahead on demonstrated mastery, or dwell on a shaky
concept.

The MVP planner is trivially simple: it returns a fixed ordering for a
known domain. The post-MVP planner is a graph walker over a concept
dependency DAG. Both fit behind the same interface.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.profile.model import Domain, LearnerProfile


class Pathway(BaseModel):
    """An ordered sequence of concepts for a domain."""

    model_config = ConfigDict(frozen=True)

    domain: Domain
    concepts: tuple[str, ...]
    position: int = 0

    def current(self) -> str | None:
        if 0 <= self.position < len(self.concepts):
            return self.concepts[self.position]
        return None

    def advanced(self) -> Pathway:
        return Pathway(
            domain=self.domain,
            concepts=self.concepts,
            position=self.position + 1,
        )


# MVP concept order for US History. Concept IDs match those used by the
# assessment and content libraries so cross-references are cheap.
_US_HISTORY_PATHWAY: tuple[str, ...] = (
    "declaration_of_independence_purpose",
    "declaration_of_independence_contradictions",
    "revolution_as_modern",
)


_PATHWAYS: dict[Domain, tuple[str, ...]] = {
    Domain.US_HISTORY: _US_HISTORY_PATHWAY,
}


class PathwayPlanner(BaseModel):
    """Produces pathways for a domain.

    Stateless. In MVP the planner ignores the learner profile — every
    student sees the same ordering. Post-MVP, profile.misconceptions and
    profile.zpd_by_domain will shape the ordering per learner.
    """

    model_config = ConfigDict(frozen=True)

    overrides: dict[Domain, tuple[str, ...]] = Field(default_factory=dict)

    def plan(self, domain: Domain, profile: LearnerProfile | None = None) -> Pathway:
        concepts = self.overrides.get(domain) or _PATHWAYS.get(domain)
        if not concepts:
            raise ValueError(f"no pathway defined for domain: {domain}")
        return Pathway(domain=domain, concepts=concepts)

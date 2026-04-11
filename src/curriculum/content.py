"""Learning-block content and modality matching.

A **learning block** is the atomic unit of instruction Stuart shows a
student in a session: a short reading, a Socratic dialogue prompt, a
primary source with scaffolding questions, etc. Each block is tagged
with a modality and a complexity tier so the engagement loop can pick
the right one without re-parsing the content.

The MVP ships with a seed library (enough to run one full session
end-to-end on US History). The post-MVP content pipeline adds
LLM-generated blocks grounded in primary-source material.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from src.profile.model import ComplexityTier, Domain, Modality


class LearningBlock(BaseModel):
    """A single instructional unit Stuart can present."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    domain: Domain
    modality: Modality
    tier: ComplexityTier
    concept: str
    title: str
    body: str
    estimated_minutes: int = 10
    source_ids: tuple[str, ...] = Field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Seed library — minimal viable content for the MVP US History session.
# ---------------------------------------------------------------------------

_DECLARATION_SOCRATIC = LearningBlock(
    domain=Domain.US_HISTORY,
    modality=Modality.SOCRATIC_DIALOGUE,
    tier=ComplexityTier.MEETING,
    concept="declaration_of_independence_purpose",
    title="Why write a declaration at all?",
    body=(
        "Imagine you've decided to quit a group you've been part of for a "
        "long time. You could just leave — or you could write a letter "
        "explaining why. What would the letter accomplish that walking away "
        "wouldn't?\n\n"
        "Hold that answer. Now: the colonists had been at war with Britain "
        "for over a year before the Declaration was adopted. They were "
        "already fighting. Why stop and write a document?"
    ),
    estimated_minutes=8,
)

_DECLARATION_SOURCE = LearningBlock(
    domain=Domain.US_HISTORY,
    modality=Modality.PRIMARY_SOURCE,
    tier=ComplexityTier.MEETING,
    concept="declaration_of_independence_purpose",
    title="Reading the Declaration — the preamble",
    body=(
        'Read this passage carefully:\n\n'
        '"When in the Course of human events, it becomes necessary for one '
        'people to dissolve the political bands which have connected them '
        'with another, and to assume among the powers of the earth, the '
        'separate and equal station to which the Laws of Nature and of '
        "Nature's God entitle them, a decent respect to the opinions of "
        "mankind requires that they should declare the causes which impel "
        'them to the separation."\n\n'
        "Use HAPP: who is the audience? What is the purpose? What does the "
        "phrase 'a decent respect to the opinions of mankind' tell you about "
        "who Jefferson expected to read this document?"
    ),
    source_ids=("declaration_preamble",),
    estimated_minutes=12,
)

_DECLARATION_VISUAL = LearningBlock(
    domain=Domain.US_HISTORY,
    modality=Modality.VISUAL_SPATIAL,
    tier=ComplexityTier.APPROACHING,
    concept="declaration_of_independence_purpose",
    title="A timeline of the break",
    body=(
        "Picture a timeline from 1763 to 1783. Place these events on it "
        "in order:\n"
        "- French and Indian War ends (1763)\n"
        "- Stamp Act (1765)\n"
        "- Boston Massacre (1770)\n"
        "- Boston Tea Party (1773)\n"
        "- First shots at Lexington and Concord (1775)\n"
        "- Declaration of Independence (1776)\n"
        "- Treaty of Paris (1783)\n\n"
        "Notice where the Declaration falls in that timeline. What does its "
        "position tell you about what it was and wasn't?"
    ),
    estimated_minutes=10,
)

_DECLARATION_WORKED = LearningBlock(
    domain=Domain.US_HISTORY,
    modality=Modality.WORKED_EXAMPLE,
    tier=ComplexityTier.APPROACHING,
    concept="declaration_of_independence_purpose",
    title="HAPP — a worked example",
    body=(
        "Here's how a historian applies HAPP to the Declaration:\n\n"
        "- **Historical context:** July 1776, over a year into armed "
        "conflict with Britain. Colonists needed foreign allies.\n"
        "- **Audience:** Three audiences at once — the British crown, "
        "potential European allies (especially France), and the colonists "
        "themselves.\n"
        "- **Purpose:** To justify separation on moral and legal grounds, "
        "not just political ones.\n"
        "- **Point of view:** Written by Jefferson, a slaveholder, claiming "
        "'all men are created equal' — a tension the document does not "
        "resolve.\n\n"
        "Now pick one of those four points and explain, in your own words, "
        "why it matters."
    ),
    estimated_minutes=10,
)


_SEED_BLOCKS: tuple[LearningBlock, ...] = (
    _DECLARATION_SOCRATIC,
    _DECLARATION_SOURCE,
    _DECLARATION_VISUAL,
    _DECLARATION_WORKED,
)


class ContentSelector:
    """Chooses the best learning block for a given (domain, modality, tier).

    Exact matches win. If no exact match exists, the selector falls back
    along an explicit priority order (tier match first, then concept
    match, then domain match) so the session loop can always make
    forward progress rather than crashing.
    """

    def __init__(self, blocks: Iterable[LearningBlock] | None = None) -> None:
        self._blocks: tuple[LearningBlock, ...] = tuple(blocks) if blocks else _SEED_BLOCKS

    @property
    def blocks(self) -> tuple[LearningBlock, ...]:
        return self._blocks

    def select(
        self,
        *,
        domain: Domain,
        modality: Modality,
        tier: ComplexityTier,
        concept: str | None = None,
        exclude_ids: frozenset[str] = frozenset(),
    ) -> LearningBlock | None:
        """Return the best-matching unused block, or None if nothing fits."""
        candidates = [b for b in self._blocks if b.id not in exclude_ids and b.domain is domain]
        if not candidates:
            return None

        exact = [
            b for b in candidates
            if b.modality is modality and b.tier is tier
            and (concept is None or b.concept == concept)
        ]
        if exact:
            return exact[0]

        modality_and_concept = [
            b for b in candidates
            if b.modality is modality
            and (concept is None or b.concept == concept)
        ]
        if modality_and_concept:
            return modality_and_concept[0]

        modality_only = [b for b in candidates if b.modality is modality]
        if modality_only:
            return modality_only[0]

        if concept is not None:
            concept_only = [b for b in candidates if b.concept == concept]
            if concept_only:
                return concept_only[0]

        return candidates[0]

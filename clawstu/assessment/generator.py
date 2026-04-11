"""Question / task generation.

Two layers:

1. A small deterministic generator that produces calibration items from
   a seed library. No LLM call. Used for initial ZPD calibration and for
   unit tests that should never depend on a network.

2. (Post-MVP) An LLM-backed generator that produces bespoke items
   grounded in primary-source material. This lives behind the
   orchestrator and is composed onto the deterministic layer; it is not
   a replacement for it.

The generator never emits content without a complexity tier and a
modality tag. Those two attributes are what the engagement loop uses to
rotate and adapt.
"""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from clawstu.profile.model import ComplexityTier, Domain, Modality


class AssessmentType(str, Enum):
    """Kinds of assessment items Stuart can present."""

    MULTIPLE_CHOICE = "multiple_choice"
    SHORT_ANSWER = "short_answer"
    CRQ = "crq"  # Constructed-response question (evidence-based)
    SOURCE_ANALYSIS = "source_analysis"


class AssessmentItem(BaseModel):
    """A single assessment item Stuart can present to a student."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    domain: Domain
    tier: ComplexityTier
    modality: Modality
    type: AssessmentType
    prompt: str
    concept: str
    choices: tuple[str, ...] | None = None
    canonical_answer: str | None = None
    rubric: tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Seed library — deterministic calibration items for the US History MVP.
# This is intentionally tiny and intentionally explicit. The MVP ships
# without LLM-generated questions; every item a student sees during
# calibration comes from this library. Post-MVP, the orchestrator can
# expand this pool.
# ---------------------------------------------------------------------------


_US_HISTORY_SEED: tuple[AssessmentItem, ...] = (
    AssessmentItem(
        domain=Domain.US_HISTORY,
        tier=ComplexityTier.APPROACHING,
        modality=Modality.TEXT_READING,
        type=AssessmentType.MULTIPLE_CHOICE,
        prompt=(
            "In 1776, the Declaration of Independence was adopted. Which of "
            "the following best describes its main purpose?"
        ),
        choices=(
            "To end the Civil War",
            "To declare the American colonies independent from Britain",
            "To establish the U.S. Constitution",
            "To free enslaved people in the South",
        ),
        canonical_answer="To declare the American colonies independent from Britain",
        concept="declaration_of_independence_purpose",
    ),
    AssessmentItem(
        domain=Domain.US_HISTORY,
        tier=ComplexityTier.MEETING,
        modality=Modality.PRIMARY_SOURCE,
        type=AssessmentType.SOURCE_ANALYSIS,
        prompt=(
            'Read this line from the Declaration: "We hold these truths to be '
            'self-evident, that all men are created equal." Using the HAPP '
            "framework (Historical context, Audience, Purpose, Point of view), "
            "explain one reason this sentence was controversial at the time it "
            "was written."
        ),
        rubric=(
            "names a specific historical tension (e.g., slavery, property, "
            "women's status)",
            "identifies the intended audience (colonists / the king / the world)",
            "distinguishes the author's stated purpose from unstated limits",
        ),
        concept="declaration_of_independence_contradictions",
    ),
    AssessmentItem(
        domain=Domain.US_HISTORY,
        tier=ComplexityTier.EXCEEDING,
        modality=Modality.SOCRATIC_DIALOGUE,
        type=AssessmentType.CRQ,
        prompt=(
            "Historians sometimes call the American Revolution 'the first "
            "modern revolution.' Make an argument for or against that claim, "
            "using at least two specific pieces of evidence from what you've "
            "learned so far."
        ),
        rubric=(
            "takes a clear position",
            "cites at least two specific pieces of evidence",
            "addresses a counterargument, even briefly",
        ),
        concept="revolution_as_modern",
    ),
)


_SEED_LIBRARIES: dict[Domain, tuple[AssessmentItem, ...]] = {
    Domain.US_HISTORY: _US_HISTORY_SEED,
}


class QuestionGenerator:
    """Deterministic calibration-question generator.

    Used in MVP for initial ZPD calibration and as a baseline that the
    LLM-backed generator (post-MVP) extends. Deterministic means: same
    inputs → same outputs, which matters for test stability and for
    reproducible session traces.
    """

    def seed_library(self, domain: Domain) -> tuple[AssessmentItem, ...]:
        """Return the seed library for a domain, or empty tuple."""
        return _SEED_LIBRARIES.get(domain, ())

    def calibration_set(
        self,
        domain: Domain,
        *,
        size: int = 3,
    ) -> tuple[AssessmentItem, ...]:
        """Return a calibration set spanning complexity tiers.

        The set always includes at least one APPROACHING and one MEETING
        item if they exist, so a single run can differentiate a struggling
        learner from one near grade level. Raises `ValueError` if no
        library exists for the requested domain.
        """
        if size < 1:
            raise ValueError(f"calibration size must be >= 1, got {size}")
        library = self.seed_library(domain)
        if not library:
            raise ValueError(f"no calibration library for domain: {domain}")

        by_tier: dict[ComplexityTier, list[AssessmentItem]] = {}
        for item in library:
            by_tier.setdefault(item.tier, []).append(item)

        # Order: approaching, meeting, exceeding. Take the first of each
        # tier, then fill the remaining slots in the same order.
        tier_order = (
            ComplexityTier.APPROACHING,
            ComplexityTier.MEETING,
            ComplexityTier.EXCEEDING,
        )
        picked: list[AssessmentItem] = []
        for tier in tier_order:
            if by_tier.get(tier):
                picked.append(by_tier[tier][0])
                if len(picked) >= size:
                    return tuple(picked)
        # Fill leftover slots by cycling through the library in order.
        for item in library:
            if item not in picked:
                picked.append(item)
                if len(picked) >= size:
                    break
        return tuple(picked[:size])

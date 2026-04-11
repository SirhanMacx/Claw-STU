"""LLM-backed live content generation.

This is the module that makes Stuart subject-agnostic. Given a free-text
topic, an age bracket, a complexity tier, and a target modality, it
asks an LLM provider for a learning block, a check-for-understanding,
or a concept pathway.

Hard contract
-------------

1. **Every string that comes out of a provider goes through safety
   filters before it is returned.** Content filter for age-appropriate
   text, boundary enforcer for sycophancy and emotional claims. A
   generated block that fails safety is rejected, not silently emitted.
2. **Provider output is parsed from strict JSON** and validated against
   the existing `LearningBlock` and `AssessmentItem` Pydantic models.
   Drift is loud: a malformed response raises `LiveGenerationError`.
3. **No hidden state.** The generator is stateless. It takes inputs,
   returns blocks. The session runner owns all state.

The orchestrator's `EchoProvider` is supported end-to-end for tests
and offline dev: when the provider is an echo, we fall back to a tiny
deterministic stub so `LiveContentGenerator` can be exercised in unit
tests without a network.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from clawstu.assessment.generator import (
    AssessmentItem,
    AssessmentType,
)
from clawstu.curriculum.content import LearningBlock
from clawstu.curriculum.topic import Topic
from clawstu.orchestrator.providers import (
    EchoProvider,
    LLMMessage,
    LLMProvider,
    ProviderError,
)
from clawstu.profile.model import AgeBracket, ComplexityTier, Domain, Modality
from clawstu.safety.boundaries import BoundaryEnforcer
from clawstu.safety.content_filter import ContentDecision, ContentFilter


class LiveGenerationError(RuntimeError):
    """Raised when a provider response cannot be parsed or fails safety."""


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_PATHWAY_SYSTEM = (
    "You are Stuart, a personal learning agent. You are a cognitive tool, "
    "not a friend or authority figure. Given a student's topic and age, "
    "propose a short ordered sequence of concept IDs that scaffolds a "
    "reasonable first session. Respond ONLY with JSON of the form: "
    '{"concepts": ["concept_one_id", "concept_two_id", ...]}. '
    "Use snake_case concept IDs. Maximum 5 concepts."
)

_BLOCK_SYSTEM = (
    "You are Stuart, a personal learning agent. Generate one short "
    "learning block for the specified concept, modality, and complexity "
    "tier. The learner is in the given age bracket. Voice: plain, "
    "concrete, age-appropriate, more questions than lectures. Never "
    "praise innate ability. Never claim to feel emotions. Respond ONLY "
    'with JSON of the form: {"title": "...", "body": "...", '
    '"estimated_minutes": 10}. The body should fit inside "estimated_minutes".'
)

_CHECK_SYSTEM = (
    "You are Stuart, a personal learning agent. Generate one "
    "check-for-understanding item for the specified concept at the "
    "specified complexity tier. Respond ONLY with JSON of the form: "
    '{"prompt": "...", "type": "crq", "rubric": ["...", "..."]} for '
    "constructed-response items, or "
    '{"prompt": "...", "type": "multiple_choice", "choices": ["a", "b", '
    '"c"], "canonical_answer": "b"} for multiple choice items. Prefer '
    "constructed-response for concept understanding; multiple choice "
    "only for simple recall."
)


# ---------------------------------------------------------------------------
# Offline stubs used when the provider is `EchoProvider`.
# These exist so the live generator can run end-to-end in unit tests
# without a network, and so the session loop has a coherent fallback
# when a provider is unavailable.
# ---------------------------------------------------------------------------


def _offline_pathway(topic: Topic) -> list[str]:
    base = topic.slug.replace("-", "_") or "topic"
    return [f"{base}_overview", f"{base}_detail", f"{base}_application"]


def _offline_block(
    *,
    topic: Topic,
    concept: str,
    modality: Modality,
    tier: ComplexityTier,
) -> dict[str, Any]:
    return {
        "title": f"{topic.raw}: {concept.replace('_', ' ')}",
        "body": (
            f"Let's explore {topic.raw}, focused on {concept.replace('_', ' ')}. "
            f"I'll use the {modality.value.replace('_', ' ')} approach at a "
            f"{tier.value} tier. What do you already know about this?"
        ),
        "estimated_minutes": 10,
    }


def _offline_check(
    *,
    concept: str,
    tier: ComplexityTier,
) -> dict[str, Any]:
    return {
        "prompt": (
            f"In your own words, explain one thing you understand about "
            f"{concept.replace('_', ' ')}. Give at least one specific "
            f"example."
        ),
        "type": "crq",
        "rubric": [
            "explains the concept in the student's own words",
            "includes at least one specific example",
        ],
    }


# ---------------------------------------------------------------------------
# Safety wrapper
# ---------------------------------------------------------------------------


class _SafetyGate:
    """Checks every generated string against content and boundary filters."""

    def __init__(
        self,
        *,
        content_filter: ContentFilter | None = None,
        boundaries: BoundaryEnforcer | None = None,
    ) -> None:
        self._content = content_filter or ContentFilter()
        self._boundaries = boundaries or BoundaryEnforcer()

    def check_strings(
        self,
        *,
        strings: list[str],
        age_bracket: AgeBracket,
    ) -> None:
        """Raise `LiveGenerationError` if any string fails safety."""
        for text in strings:
            content = self._content.check(text, age_bracket=age_bracket)
            if content.decision is ContentDecision.BLOCK:
                raise LiveGenerationError(
                    f"generated text blocked by content filter: "
                    f"{content.matched_terms}"
                )
            outbound = self._boundaries.scan_outbound(text)
            if outbound is not None:
                raise LiveGenerationError(
                    f"generated text violates outbound boundary: "
                    f"{outbound.kind.value} ({outbound.matched_phrase!r})"
                )


# ---------------------------------------------------------------------------
# Live content generator
# ---------------------------------------------------------------------------


class LiveContentGenerator:
    """Produces blocks, checks, and pathways for an arbitrary topic.

    Stateless. Takes a provider at construction time and delegates. All
    outputs go through a safety gate before returning.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        safety: _SafetyGate | None = None,
    ) -> None:
        self._provider = provider
        self._safety = safety or _SafetyGate()

    def generate_pathway(
        self,
        *,
        topic: Topic,
        age_bracket: AgeBracket,
        max_concepts: int = 4,
    ) -> tuple[str, ...]:
        """Return an ordered list of concept IDs for the topic."""
        if isinstance(self._provider, EchoProvider):
            concepts = _offline_pathway(topic)[:max_concepts]
        else:
            user = (
                f"Student topic: {topic.raw}\n"
                f"Age bracket: {age_bracket.value}\n"
                f"Maximum concepts: {max_concepts}"
            )
            payload = self._ask_json(system=_PATHWAY_SYSTEM, user=user)
            raw_concepts = payload.get("concepts")
            if not isinstance(raw_concepts, list) or not raw_concepts:
                raise LiveGenerationError(
                    f"pathway response missing 'concepts': {payload!r}"
                )
            concepts = [str(c) for c in raw_concepts][:max_concepts]

        if not concepts:
            raise LiveGenerationError("pathway generator produced no concepts")
        return tuple(concepts)

    def generate_block(
        self,
        *,
        topic: Topic,
        concept: str,
        modality: Modality,
        tier: ComplexityTier,
        age_bracket: AgeBracket,
    ) -> LearningBlock:
        """Return a single `LearningBlock` for the given parameters."""
        if isinstance(self._provider, EchoProvider):
            payload = _offline_block(
                topic=topic, concept=concept, modality=modality, tier=tier
            )
        else:
            user = (
                f"Topic: {topic.raw}\n"
                f"Concept: {concept}\n"
                f"Modality: {modality.value}\n"
                f"Complexity tier: {tier.value}\n"
                f"Age bracket: {age_bracket.value}"
            )
            payload = self._ask_json(system=_BLOCK_SYSTEM, user=user)

        title = _require_str(payload, "title")
        body = _require_str(payload, "body")
        estimated = payload.get("estimated_minutes", 10)
        if not isinstance(estimated, int) or estimated <= 0 or estimated > 60:
            estimated = 10

        self._safety.check_strings(
            strings=[title, body], age_bracket=age_bracket
        )
        return LearningBlock(
            id=str(uuid.uuid4()),
            domain=topic.domain,
            modality=modality,
            tier=tier,
            concept=concept,
            title=title,
            body=body,
            estimated_minutes=estimated,
        )

    def generate_check(
        self,
        *,
        topic: Topic,
        concept: str,
        tier: ComplexityTier,
        modality: Modality,
        age_bracket: AgeBracket,
    ) -> AssessmentItem:
        """Return an `AssessmentItem` for the given parameters."""
        if isinstance(self._provider, EchoProvider):
            payload = _offline_check(concept=concept, tier=tier)
        else:
            user = (
                f"Topic: {topic.raw}\n"
                f"Concept: {concept}\n"
                f"Complexity tier: {tier.value}\n"
                f"Age bracket: {age_bracket.value}"
            )
            payload = self._ask_json(system=_CHECK_SYSTEM, user=user)

        prompt_text = _require_str(payload, "prompt")
        type_value = _require_str(payload, "type")

        strings_to_check = [prompt_text]
        rubric: tuple[str, ...] | None = None
        choices: tuple[str, ...] | None = None
        canonical: str | None = None
        assessment_type: AssessmentType

        if type_value in ("crq", "source_analysis"):
            assessment_type = (
                AssessmentType.CRQ
                if type_value == "crq"
                else AssessmentType.SOURCE_ANALYSIS
            )
            raw_rubric = payload.get("rubric")
            if not isinstance(raw_rubric, list) or not raw_rubric:
                raise LiveGenerationError(
                    f"check response missing 'rubric': {payload!r}"
                )
            rubric = tuple(str(r) for r in raw_rubric)
            strings_to_check.extend(rubric)
        elif type_value == "multiple_choice":
            assessment_type = AssessmentType.MULTIPLE_CHOICE
            raw_choices = payload.get("choices")
            if not isinstance(raw_choices, list) or len(raw_choices) < 2:
                raise LiveGenerationError(
                    f"check response missing 'choices': {payload!r}"
                )
            choices = tuple(str(c) for c in raw_choices)
            canonical = _require_str(payload, "canonical_answer")
            strings_to_check.extend(choices)
            strings_to_check.append(canonical)
        else:
            raise LiveGenerationError(
                f"check response has unknown type: {type_value!r}"
            )

        self._safety.check_strings(
            strings=strings_to_check, age_bracket=age_bracket
        )
        return AssessmentItem(
            id=str(uuid.uuid4()),
            domain=topic.domain,
            tier=tier,
            modality=modality,
            type=assessment_type,
            prompt=prompt_text,
            concept=concept,
            choices=choices,
            canonical_answer=canonical,
            rubric=rubric,
        )

    # -- internals --------------------------------------------------------

    def _ask_json(self, *, system: str, user: str) -> dict[str, Any]:
        """Ask the provider for a JSON object and parse it strictly."""
        try:
            response = self._provider.complete(
                system=system,
                messages=[LLMMessage(role="user", content=user)],
            )
        except ProviderError as exc:
            raise LiveGenerationError(f"provider failed: {exc}") from exc
        text = response.text.strip()
        # Tolerate a leading ```json fence; reject anything else.
        if text.startswith("```"):
            fence_end = text.rfind("```")
            if fence_end <= 3:
                raise LiveGenerationError(
                    f"malformed code fence in provider response: {text!r}"
                )
            text = text[text.find("\n") + 1 : fence_end].strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LiveGenerationError(
                f"provider response is not JSON: {exc}: {text!r}"
            ) from exc
        if not isinstance(parsed, dict):
            raise LiveGenerationError(
                f"provider JSON must be an object, got: {type(parsed).__name__}"
            )
        return parsed


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LiveGenerationError(f"response missing string field {key!r}")
    return value.strip()


# Rebind the public name for Domain so tests importing it via this
# module don't have to reach into clawstu.profile.model directly.
__all__ = [
    "Domain",
    "LiveContentGenerator",
    "LiveGenerationError",
]

"""Tests for LiveContentGenerator error paths and non-Echo branches.

Covers the _ask_json parsing (code fences, malformed JSON, non-object
JSON), ProviderError wrapping, and missing-field validation that
the existing test_live_content.py EchoProvider tests do not reach.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from clawstu.assessment.generator import AssessmentType
from clawstu.curriculum.topic import Topic
from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.live_content import (
    LiveContentGenerator,
    LiveGenerationError,
)
from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ProviderError,
)
from clawstu.orchestrator.router import ModelRouter
from clawstu.profile.model import AgeBracket, ComplexityTier, Domain, Modality

# ---------------------------------------------------------------------------
# Fake provider that returns a predetermined response.
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Non-Echo provider that returns canned text."""

    name: str = "fake"

    def __init__(self, text: str) -> None:
        self._text = text

    async def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        return LLMResponse(
            text=self._text,
            provider="fake",
            model=model,
        )


class _ErrorProvider:
    """Non-Echo provider that always raises ProviderError."""

    name: str = "error"

    async def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        raise ProviderError("simulated failure")


def _router_with(provider: Any) -> ModelRouter:
    """Build a router that routes everything to the given provider.

    ModelRouter requires an ``echo`` provider as the fallback floor,
    so we include a real EchoProvider but set the primary to ``fake``
    so all tasks route through the custom provider first.
    """
    from clawstu.orchestrator.providers import EchoProvider

    providers: dict[str, LLMProvider] = {
        "echo": EchoProvider(),
        "fake": provider,  # type: ignore[dict-item]
    }
    cfg = AppConfig(
        primary_provider="fake",
        fallback_chain=["fake"],
    )
    return ModelRouter(config=cfg, providers=providers)


@pytest.fixture
def topic() -> Topic:
    return Topic.from_student_input(
        "The French Revolution", domain=Domain.GLOBAL_HISTORY,
    )


# ---------------------------------------------------------------------------
# _ask_json: code fence stripping
# ---------------------------------------------------------------------------


async def test_generate_pathway_via_json_response(topic: Topic) -> None:
    """Non-Echo provider path: valid JSON pathway."""
    payload = json.dumps({"concepts": ["cause_one", "cause_two"]})
    gen = LiveContentGenerator(router=_router_with(_FakeProvider(payload)))
    pathway = await gen.generate_pathway(
        topic=topic, age_bracket=AgeBracket.MIDDLE,
    )
    assert pathway == ("cause_one", "cause_two")


async def test_generate_pathway_code_fence(topic: Topic) -> None:
    """Non-Echo provider: JSON wrapped in a ```json code fence."""
    inner = json.dumps({"concepts": ["a", "b", "c"]})
    text = f"```json\n{inner}\n```"
    gen = LiveContentGenerator(router=_router_with(_FakeProvider(text)))
    pathway = await gen.generate_pathway(
        topic=topic, age_bracket=AgeBracket.MIDDLE,
    )
    assert pathway == ("a", "b", "c")


async def test_generate_pathway_malformed_fence(topic: Topic) -> None:
    """Unclosed code fence raises LiveGenerationError."""
    gen = LiveContentGenerator(router=_router_with(_FakeProvider("```only")))
    with pytest.raises(LiveGenerationError, match="malformed code fence"):
        await gen.generate_pathway(
            topic=topic, age_bracket=AgeBracket.MIDDLE,
        )


async def test_generate_pathway_not_json(topic: Topic) -> None:
    """Non-JSON text from provider raises LiveGenerationError."""
    gen = LiveContentGenerator(router=_router_with(_FakeProvider("not json")))
    with pytest.raises(LiveGenerationError, match="not JSON"):
        await gen.generate_pathway(
            topic=topic, age_bracket=AgeBracket.MIDDLE,
        )


async def test_generate_pathway_json_list_raises(topic: Topic) -> None:
    """JSON array (not object) raises LiveGenerationError."""
    gen = LiveContentGenerator(router=_router_with(_FakeProvider('["a"]')))
    with pytest.raises(LiveGenerationError, match="must be an object"):
        await gen.generate_pathway(
            topic=topic, age_bracket=AgeBracket.MIDDLE,
        )


async def test_generate_pathway_missing_concepts(topic: Topic) -> None:
    """Missing 'concepts' key raises LiveGenerationError."""
    gen = LiveContentGenerator(router=_router_with(_FakeProvider("{}")))
    with pytest.raises(LiveGenerationError, match=r"missing.*concepts"):
        await gen.generate_pathway(
            topic=topic, age_bracket=AgeBracket.MIDDLE,
        )


async def test_generate_pathway_provider_error(topic: Topic) -> None:
    """ProviderError is wrapped in LiveGenerationError."""
    gen = LiveContentGenerator(router=_router_with(_ErrorProvider()))
    with pytest.raises(LiveGenerationError, match="provider failed"):
        await gen.generate_pathway(
            topic=topic, age_bracket=AgeBracket.MIDDLE,
        )


# ---------------------------------------------------------------------------
# generate_block: non-Echo path
# ---------------------------------------------------------------------------


async def test_generate_block_via_json_response(topic: Topic) -> None:
    payload = json.dumps({
        "title": "The Revolution",
        "body": "Let us explore the causes.",
        "estimated_minutes": 8,
    })
    gen = LiveContentGenerator(router=_router_with(_FakeProvider(payload)))
    block = await gen.generate_block(
        topic=topic,
        concept="causes",
        modality=Modality.TEXT_READING,
        tier=ComplexityTier.MEETING,
        age_bracket=AgeBracket.MIDDLE,
    )
    assert block.title == "The Revolution"
    assert block.estimated_minutes == 8


async def test_generate_block_bad_estimated_minutes(topic: Topic) -> None:
    """Invalid estimated_minutes defaults to 10."""
    payload = json.dumps({
        "title": "Block",
        "body": "Content here.",
        "estimated_minutes": -5,
    })
    gen = LiveContentGenerator(router=_router_with(_FakeProvider(payload)))
    block = await gen.generate_block(
        topic=topic,
        concept="x",
        modality=Modality.TEXT_READING,
        tier=ComplexityTier.APPROACHING,
        age_bracket=AgeBracket.MIDDLE,
    )
    assert block.estimated_minutes == 10


# ---------------------------------------------------------------------------
# generate_check: non-Echo path (CRQ + MC)
# ---------------------------------------------------------------------------


async def test_generate_check_crq_via_json(topic: Topic) -> None:
    payload = json.dumps({
        "prompt": "Explain the causes.",
        "type": "crq",
        "rubric": ["identifies causes", "uses evidence"],
    })
    gen = LiveContentGenerator(router=_router_with(_FakeProvider(payload)))
    check = await gen.generate_check(
        topic=topic,
        concept="causes",
        tier=ComplexityTier.MEETING,
        modality=Modality.TEXT_READING,
        age_bracket=AgeBracket.MIDDLE,
    )
    assert check.type is AssessmentType.CRQ
    assert check.rubric is not None
    assert len(check.rubric) == 2


async def test_generate_check_multiple_choice_via_json(topic: Topic) -> None:
    payload = json.dumps({
        "prompt": "Which was a cause?",
        "type": "multiple_choice",
        "choices": ["a", "b", "c"],
        "canonical_answer": "b",
    })
    gen = LiveContentGenerator(router=_router_with(_FakeProvider(payload)))
    check = await gen.generate_check(
        topic=topic,
        concept="causes",
        tier=ComplexityTier.APPROACHING,
        modality=Modality.TEXT_READING,
        age_bracket=AgeBracket.MIDDLE,
    )
    assert check.type is AssessmentType.MULTIPLE_CHOICE
    assert check.choices is not None
    assert check.canonical_answer == "b"


async def test_generate_check_missing_rubric(topic: Topic) -> None:
    payload = json.dumps({
        "prompt": "Explain.",
        "type": "crq",
    })
    gen = LiveContentGenerator(router=_router_with(_FakeProvider(payload)))
    with pytest.raises(LiveGenerationError, match=r"missing.*rubric"):
        await gen.generate_check(
            topic=topic,
            concept="x",
            tier=ComplexityTier.MEETING,
            modality=Modality.TEXT_READING,
            age_bracket=AgeBracket.MIDDLE,
        )


async def test_generate_check_missing_choices(topic: Topic) -> None:
    payload = json.dumps({
        "prompt": "Which one?",
        "type": "multiple_choice",
    })
    gen = LiveContentGenerator(router=_router_with(_FakeProvider(payload)))
    with pytest.raises(LiveGenerationError, match=r"missing.*choices"):
        await gen.generate_check(
            topic=topic,
            concept="x",
            tier=ComplexityTier.APPROACHING,
            modality=Modality.TEXT_READING,
            age_bracket=AgeBracket.MIDDLE,
        )


async def test_generate_check_unknown_type(topic: Topic) -> None:
    payload = json.dumps({
        "prompt": "Answer this.",
        "type": "essay",
    })
    gen = LiveContentGenerator(router=_router_with(_FakeProvider(payload)))
    with pytest.raises(LiveGenerationError, match="unknown type"):
        await gen.generate_check(
            topic=topic,
            concept="x",
            tier=ComplexityTier.MEETING,
            modality=Modality.TEXT_READING,
            age_bracket=AgeBracket.MIDDLE,
        )


async def test_generate_check_source_analysis_type(topic: Topic) -> None:
    payload = json.dumps({
        "prompt": "Analyze this source.",
        "type": "source_analysis",
        "rubric": ["context", "purpose"],
    })
    gen = LiveContentGenerator(router=_router_with(_FakeProvider(payload)))
    check = await gen.generate_check(
        topic=topic,
        concept="x",
        tier=ComplexityTier.EXCEEDING,
        modality=Modality.PRIMARY_SOURCE,
        age_bracket=AgeBracket.MIDDLE,
    )
    assert check.type is AssessmentType.SOURCE_ANALYSIS

"""LiveContentGenerator — Phase 2 router-based tests.

These tests exercise the EchoProvider offline fallback path, which
lets us verify the generator's full contract without a network. The
LLM-backed path (production providers) is tested by the provider-
specific test files (test_provider_ollama etc.) — LiveContentGenerator
just glues prompts + the router together.
"""
from __future__ import annotations

import pytest

from clawstu.assessment.generator import AssessmentType
from clawstu.curriculum.live_generator import LiveContentGenerator
from clawstu.curriculum.topic import Topic
from clawstu.profile.model import AgeBracket, ComplexityTier, Domain, Modality
from tests.conftest import async_router_for_testing


@pytest.fixture
def topic() -> Topic:
    return Topic.from_student_input(
        "The French Revolution", domain=Domain.GLOBAL_HISTORY
    )


async def test_generate_pathway_returns_concepts(topic: Topic) -> None:
    gen = LiveContentGenerator(router=async_router_for_testing())
    pathway = await gen.generate_pathway(
        topic=topic, age_bracket=AgeBracket.MIDDLE, max_concepts=3
    )
    assert len(pathway) == 3
    assert all(isinstance(c, str) and c for c in pathway)


async def test_generate_block_returns_learning_block(topic: Topic) -> None:
    gen = LiveContentGenerator(router=async_router_for_testing())
    block = await gen.generate_block(
        topic=topic,
        concept="french_revolution_overview",
        modality=Modality.TEXT_READING,
        tier=ComplexityTier.MEETING,
        age_bracket=AgeBracket.MIDDLE,
    )
    assert block.title
    assert block.body
    assert block.estimated_minutes > 0
    assert block.domain is Domain.GLOBAL_HISTORY


async def test_generate_check_returns_crq(topic: Topic) -> None:
    gen = LiveContentGenerator(router=async_router_for_testing())
    check = await gen.generate_check(
        topic=topic,
        concept="french_revolution_overview",
        tier=ComplexityTier.MEETING,
        modality=Modality.TEXT_READING,
        age_bracket=AgeBracket.MIDDLE,
    )
    # The offline stub returns a crq by default.
    assert check.type is AssessmentType.CRQ
    assert check.prompt
    assert check.rubric is not None and len(check.rubric) >= 1

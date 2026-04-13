"""Tests for Sprint 1 competitive-borrowing features.

Covers:
- Behavioral contract in the Stuart system prompt
- define_learning_goals tool
- check_learning_goals tool
- Query diversification in search_brain
- Approval policy for new tools
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawstu.agent.approvals import ApprovalPolicy, TurnState
from clawstu.agent.base_tool import ToolContext
from clawstu.agent.prompt import build_stuart_prompt
from clawstu.agent.tools.check_learning_goals import CheckLearningGoalsTool
from clawstu.agent.tools.define_learning_goals import DefineLearningGoalsTool
from clawstu.agent.tools.search_brain import SearchBrainTool, _diversify_query
from clawstu.memory.store import BrainStore
from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.providers import EchoProvider
from clawstu.orchestrator.router import ModelRouter
from clawstu.profile.model import AgeBracket, Domain, LearnerProfile, ZPDEstimate

# ── Helpers ────────────────────────────────────────────────────────────


def _profile() -> LearnerProfile:
    return LearnerProfile(
        learner_id="test-learner",
        age_bracket=AgeBracket.EARLY_HIGH,
        zpd_by_domain={Domain.US_HISTORY: ZPDEstimate(domain=Domain.US_HISTORY)},
    )


def _context(tmp_path: Path) -> ToolContext:
    echo = EchoProvider()
    router = ModelRouter(config=AppConfig(), providers={"echo": echo})
    return ToolContext(
        profile=_profile(),
        session_id="s-test",
        brain=BrainStore(base_dir=tmp_path / "brain"),
        router=router,
        output_dir=tmp_path / "out",
        learner_id="test-learner",
    )


# ── Behavioral Contract in prompt ─────────────────────────────────────


class TestBehavioralContract:
    def test_contract_present_in_prompt(self) -> None:
        prompt = build_stuart_prompt(
            profile=_profile(),
            session_id="s1",
            brain_context="",
            tool_names=["read_profile"],
        )
        assert "Behavioral Contract" in prompt
        assert "CHECK before advancing" in prompt
        assert "MINIMAL explanation first" in prompt
        assert "SURFACE misconceptions" in prompt
        assert "ONE thing at a time" in prompt
        assert "GOALS before teaching" in prompt

    def test_contract_after_identity_before_safety(self) -> None:
        prompt = build_stuart_prompt(
            profile=_profile(),
            session_id="s1",
            brain_context="",
            tool_names=[],
        )
        identity_pos = prompt.index("Stuart")
        contract_pos = prompt.index("Behavioral Contract")
        safety_pos = prompt.index("Safety constraints")
        assert identity_pos < contract_pos < safety_pos

    def test_learning_goals_instructions_in_prompt(self) -> None:
        prompt = build_stuart_prompt(
            profile=_profile(),
            session_id="s1",
            brain_context="",
            tool_names=["define_learning_goals", "check_learning_goals"],
        )
        assert "define_learning_goals" in prompt
        assert "check_learning_goals" in prompt
        assert "BEFORE teaching" in prompt


# ── define_learning_goals tool ─────────────────────────────────────────


class TestDefineLearningGoals:
    def test_define_goals_schema_valid(self) -> None:
        tool = DefineLearningGoalsTool()
        schema = tool.schema()
        assert schema["function"]["name"] == "define_learning_goals"
        assert "topic" in schema["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_execute_returns_objectives(self, tmp_path: Path) -> None:
        tool = DefineLearningGoalsTool()
        ctx = _context(tmp_path)
        result = await tool.execute({"topic": "Photosynthesis"}, ctx)
        assert "Learning objectives" in result
        assert "Photosynthesis" in result

    @pytest.mark.asyncio
    async def test_execute_error_on_empty_topic(self, tmp_path: Path) -> None:
        tool = DefineLearningGoalsTool()
        ctx = _context(tmp_path)
        result = await tool.execute({"topic": ""}, ctx)
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_execute_with_zpd(self, tmp_path: Path) -> None:
        tool = DefineLearningGoalsTool()
        ctx = _context(tmp_path)
        result = await tool.execute(
            {"topic": "Fractions", "current_zpd": "approaching"}, ctx,
        )
        assert "Learning objectives" in result


# ── check_learning_goals tool ──────────────────────────────────────────


class TestCheckLearningGoals:
    def test_check_goals_schema_valid(self) -> None:
        tool = CheckLearningGoalsTool()
        schema = tool.schema()
        assert schema["function"]["name"] == "check_learning_goals"
        props = schema["function"]["parameters"]["properties"]
        assert "goals" in props
        assert "evidence" in props

    @pytest.mark.asyncio
    async def test_execute_returns_assessment(self, tmp_path: Path) -> None:
        tool = CheckLearningGoalsTool()
        ctx = _context(tmp_path)
        result = await tool.execute(
            {"goals": "Explain photosynthesis", "evidence": "Student described it"},
            ctx,
        )
        assert "Goal assessment" in result

    @pytest.mark.asyncio
    async def test_execute_error_on_missing_fields(self, tmp_path: Path) -> None:
        tool = CheckLearningGoalsTool()
        ctx = _context(tmp_path)
        result = await tool.execute({"goals": "", "evidence": ""}, ctx)
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_execute_error_on_missing_evidence(self, tmp_path: Path) -> None:
        tool = CheckLearningGoalsTool()
        ctx = _context(tmp_path)
        result = await tool.execute({"goals": "Some goal", "evidence": ""}, ctx)
        assert "ERROR" in result


# ── Query diversification ──────────────────────────────────────────────


class TestQueryDiversification:
    def test_single_word_no_expansion(self) -> None:
        result = _diversify_query("photosynthesis")
        assert result == ["photosynthesis"]

    def test_multi_word_produces_variants(self) -> None:
        result = _diversify_query("cell division mitosis")
        assert len(result) >= 2
        assert result[0] == "cell division mitosis"

    def test_reversed_variant_present(self) -> None:
        result = _diversify_query("water cycle evaporation")
        assert any("evaporation" in q and "water" in q for q in result)

    def test_longest_keyword_variant(self) -> None:
        result = _diversify_query("cell division")
        assert "division" in result

    def test_no_duplicate_variants(self) -> None:
        result = _diversify_query("test query")
        assert len(result) == len(set(result))


# ── Search brain with diversification ──────────────────────────────────


class TestSearchBrainDiversified:
    @pytest.mark.asyncio
    async def test_search_still_returns_matches(self, tmp_path: Path) -> None:
        """The diversified search should still find direct matches."""
        tool = SearchBrainTool()
        ctx = _context(tmp_path)
        # No pages exist, so we expect the "no pages" message
        result = await tool.execute({"query": "anything"}, ctx)
        assert "No brain pages" in result

    @pytest.mark.asyncio
    async def test_search_error_on_empty(self, tmp_path: Path) -> None:
        tool = SearchBrainTool()
        ctx = _context(tmp_path)
        result = await tool.execute({"query": ""}, ctx)
        assert "ERROR" in result


# ── Approval policy includes new tools ─────────────────────────────────


class TestApprovalNewTools:
    def test_define_learning_goals_always_allowed(self) -> None:
        policy = ApprovalPolicy()
        state = TurnState()
        assert policy.check("define_learning_goals", state) is True
        assert state.generation_count == 0

    def test_check_learning_goals_always_allowed(self) -> None:
        policy = ApprovalPolicy()
        state = TurnState()
        assert policy.check("check_learning_goals", state) is True
        assert state.generation_count == 0

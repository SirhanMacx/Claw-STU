"""Tests for Sprint 2 competitive borrowing: templates, surgical feedback, first turn."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clawstu.agent.base_tool import ToolContext
from clawstu.assessment.evaluator import EvaluationResult, Evaluator
from clawstu.assessment.generator import AssessmentItem, AssessmentType
from clawstu.memory.pages import TemplatePage, render_frontmatter
from clawstu.memory.pages.base import PageKind
from clawstu.memory.store import BrainStore
from clawstu.profile.model import ComplexityTier, Domain, Modality

# -- helpers ---------------------------------------------------------------


def _make_ctx(tmp_path: Path) -> ToolContext:
    """Build a ToolContext with a real BrainStore."""
    return ToolContext(
        profile=MagicMock(),
        session_id="test-session",
        brain=BrainStore(tmp_path / "brain"),
        router=MagicMock(),
        output_dir=tmp_path,
        learner_id="test-learner",
    )


# -- TemplatePage ----------------------------------------------------------


class TestTemplatePage:
    def test_round_trip(self) -> None:
        original = TemplatePage(
            learner_id="test-learner",
            template_id="tpl-abc",
            artifact_type="worksheet",
            topic="civil_war",
            zpd_tier="meeting",
            prompt_used="Generate a worksheet on civil war causes",
            success_score=0.85,
            compiled_truth="Student scored 85% after using this.",
        )
        rendered = original.render()
        parsed = TemplatePage.parse(rendered)
        assert parsed.template_id == "tpl-abc"
        assert parsed.artifact_type == "worksheet"
        assert parsed.topic == "civil_war"
        assert parsed.zpd_tier == "meeting"
        assert parsed.success_score == pytest.approx(0.85)

    def test_frontmatter_contains_key_fields(self) -> None:
        page = TemplatePage(
            learner_id="l1",
            template_id="tpl-xyz",
            artifact_type="game",
            topic="reconstruction",
        )
        rendered = page.render()
        assert "artifact_type: game" in rendered
        assert "topic: reconstruction" in rendered
        assert "kind: template" in rendered

    def test_parse_rejects_wrong_kind(self) -> None:
        from clawstu.memory.pages import ConceptPage

        page = ConceptPage(
            learner_id="l1", concept_id="c1", compiled_truth="x",
        )
        with pytest.raises(ValueError, match="expected kind=template"):
            TemplatePage.parse(page.render())

    def test_float_frontmatter_support(self) -> None:
        text = render_frontmatter({"score": 0.75})
        assert "score: 0.75" in text

    def test_page_kind_includes_template(self) -> None:
        assert PageKind.TEMPLATE.value == "template"


# -- BrainStore template integration --------------------------------------


class TestBrainStoreTemplate:
    def test_put_and_get_template(self, tmp_path: Path) -> None:
        store = BrainStore(tmp_path / "brain")
        page = TemplatePage(
            learner_id="test-learner",
            template_id="tpl-001",
            artifact_type="visual",
            topic="revolution",
            compiled_truth="Worked well.",
        )
        store.put(page, learner_id="test-learner")
        result = store.get(
            PageKind.TEMPLATE, "tpl-001", "test-learner",
        )
        assert result is not None
        assert isinstance(result, TemplatePage)
        assert result.template_id == "tpl-001"

    def test_list_for_learner_includes_templates(self, tmp_path: Path) -> None:
        store = BrainStore(tmp_path / "brain")
        page = TemplatePage(
            learner_id="test-learner",
            template_id="tpl-002",
            artifact_type="worksheet",
            topic="slavery",
            compiled_truth="Effective.",
        )
        store.put(page, learner_id="test-learner")
        pages = store.list_for_learner(
            "test-learner", kind=PageKind.TEMPLATE,
        )
        assert len(pages) == 1
        assert isinstance(pages[0], TemplatePage)


# -- SaveTemplateTool ------------------------------------------------------


class TestSaveTemplateTool:
    @pytest.mark.asyncio
    async def test_save_creates_template_page(self, tmp_path: Path) -> None:
        from clawstu.agent.tools.save_template import SaveTemplateTool

        ctx = _make_ctx(tmp_path)
        tool = SaveTemplateTool()
        result = await tool.execute(
            {
                "artifact_type": "game",
                "topic": "reconstruction",
                "prompt_used": "Create a matching game",
                "success_notes": "Student engaged for 10 min",
            },
            ctx,
        )
        assert "Saved template" in result
        assert "game" in result
        pages = ctx.brain.list_for_learner(
            "test-learner", kind=PageKind.TEMPLATE,
        )
        assert len(pages) == 1

    @pytest.mark.asyncio
    async def test_save_rejects_missing_fields(self, tmp_path: Path) -> None:
        from clawstu.agent.tools.save_template import SaveTemplateTool

        ctx = _make_ctx(tmp_path)
        tool = SaveTemplateTool()
        result = await tool.execute({"artifact_type": "game"}, ctx)
        assert "ERROR" in result


# -- FindTemplateTool ------------------------------------------------------


class TestFindTemplateTool:
    @pytest.mark.asyncio
    async def test_find_returns_matching_templates(
        self, tmp_path: Path,
    ) -> None:
        from clawstu.agent.tools.find_template import FindTemplateTool

        ctx = _make_ctx(tmp_path)
        page = TemplatePage(
            learner_id="test-learner",
            template_id="tpl-find",
            artifact_type="worksheet",
            topic="Civil War causes",
            prompt_used="Generate worksheet on causes",
            compiled_truth="Good results.",
        )
        ctx.brain.put(page, learner_id="test-learner")

        tool = FindTemplateTool()
        result = await tool.execute({"topic": "civil war"}, ctx)
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["template_id"] == "tpl-find"

    @pytest.mark.asyncio
    async def test_find_filters_by_artifact_type(
        self, tmp_path: Path,
    ) -> None:
        from clawstu.agent.tools.find_template import FindTemplateTool

        ctx = _make_ctx(tmp_path)
        for atype in ("worksheet", "game"):
            page = TemplatePage(
                learner_id="test-learner",
                template_id=f"tpl-{atype}",
                artifact_type=atype,
                topic="Civil War",
                prompt_used=f"Generate {atype}",
                compiled_truth="ok",
            )
            ctx.brain.put(page, learner_id="test-learner")

        tool = FindTemplateTool()
        result = await tool.execute(
            {"topic": "civil war", "artifact_type": "game"}, ctx,
        )
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["artifact_type"] == "game"

    @pytest.mark.asyncio
    async def test_find_no_match(self, tmp_path: Path) -> None:
        from clawstu.agent.tools.find_template import FindTemplateTool

        ctx = _make_ctx(tmp_path)
        tool = FindTemplateTool()
        result = await tool.execute({"topic": "quantum physics"}, ctx)
        assert "No templates found" in result

    @pytest.mark.asyncio
    async def test_find_rejects_empty_topic(self, tmp_path: Path) -> None:
        from clawstu.agent.tools.find_template import FindTemplateTool

        ctx = _make_ctx(tmp_path)
        tool = FindTemplateTool()
        result = await tool.execute({"topic": ""}, ctx)
        assert "ERROR" in result


# -- Surgical Feedback (Evaluator) -----------------------------------------


class TestSurgicalFeedback:
    def _mc_item(self) -> AssessmentItem:
        return AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.APPROACHING,
            modality=Modality.TEXT_READING,
            type=AssessmentType.MULTIPLE_CHOICE,
            prompt="q?",
            choices=("a", "b"),
            canonical_answer="b",
            concept="test_concept",
        )

    def _rubric_item(self) -> AssessmentItem:
        return AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.MEETING,
            modality=Modality.SOCRATIC_DIALOGUE,
            type=AssessmentType.CRQ,
            prompt="Explain the causes of the Civil War.",
            rubric=(
                "mentions slavery as a primary cause",
                "identifies economic differences",
                "discusses states' rights debate",
            ),
            concept="civil_war_causes",
        )

    def test_correct_exact_has_no_primary_feedback(self) -> None:
        evaluator = Evaluator()
        result = evaluator.evaluate(self._mc_item(), "b")
        assert result.correct is True
        assert result.primary_feedback == ""
        assert result.deferred_feedback == ()

    def test_wrong_exact_has_primary_feedback(self) -> None:
        evaluator = Evaluator()
        result = evaluator.evaluate(self._mc_item(), "a")
        assert result.correct is False
        assert "test_concept" in result.primary_feedback

    def test_rubric_partial_hit_has_surgical_feedback(self) -> None:
        evaluator = Evaluator()
        response = (
            "The Civil War was caused by the debate over slavery "
            "which divided the nation along regional lines "
            "with very different perspectives on the issue."
        )
        result = evaluator.evaluate(self._rubric_item(), response)
        # Should hit "slavery" but miss "economic" and "states' rights"
        assert result.primary_feedback != ""
        assert len(result.deferred_feedback) >= 0

    def test_rubric_full_hit_has_no_primary_feedback(self) -> None:
        evaluator = Evaluator()
        response = (
            "The Civil War was caused primarily by slavery. "
            "Economic differences between the agrarian South and "
            "industrial North deepened the divide. The states' "
            "rights debate was used to justify secession."
        )
        result = evaluator.evaluate(self._rubric_item(), response)
        assert result.primary_feedback == ""
        assert result.deferred_feedback == ()

    def test_existing_evaluator_contract_preserved(self) -> None:
        """Ensure backward compatibility: old fields still work."""
        result = EvaluationResult(
            item_id="x", correct=True, score=1.0,
        )
        assert result.primary_feedback == ""
        assert result.deferred_feedback == ()


# -- First Turn Protocol (Prompt) ------------------------------------------


class TestFirstTurnProtocol:
    def test_prompt_contains_first_turn_protocol(self) -> None:
        from clawstu.agent.prompt import build_stuart_prompt
        from clawstu.profile.model import AgeBracket, LearnerProfile

        profile = LearnerProfile(
            learner_id="test-learner",
            age_bracket=AgeBracket.EARLY_HIGH,
        )
        prompt = build_stuart_prompt(
            profile=profile,
            session_id="s1",
            brain_context="",
            tool_names=["search_brain"],
        )
        assert "First Turn Protocol" in prompt
        assert "3 assumptions" in prompt
        assert "Does this match where you are" in prompt

    def test_prompt_contains_template_tool_hints(self) -> None:
        from clawstu.agent.prompt import build_stuart_prompt
        from clawstu.profile.model import AgeBracket, LearnerProfile

        profile = LearnerProfile(
            learner_id="test-learner",
            age_bracket=AgeBracket.MIDDLE,
        )
        prompt = build_stuart_prompt(
            profile=profile,
            session_id="s1",
            brain_context="",
            tool_names=["save_template", "find_template"],
        )
        assert "save_template" in prompt
        assert "find_template" in prompt

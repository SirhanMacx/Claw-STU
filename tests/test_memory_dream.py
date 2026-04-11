"""Dream cycle tests — report shape + error handling + empty-brain no-op."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from clawstu.memory.dream import DreamReport, dream_cycle
from clawstu.memory.pages import ConceptPage, LearnerPage, TimelineEntry
from clawstu.memory.store import BrainStore


class _StaticConsolidator:
    """Returns a fixed long paragraph regardless of input.

    Because the response is constant and long, the first run of the
    dream cycle will mark it as meaningfully different from the
    initial compiled truth and rewrite every page. A second run over
    the same brain then sees the compiled truth ALREADY matches the
    static response, so every subsequent page is skipped.
    """

    def __init__(self, text: str) -> None:
        self._text = text

    async def consolidate(self, *, system: str, user: str) -> str:
        return self._text


class _FailingConsolidator:
    """Raises on every call — exercises the error-handling path."""

    async def consolidate(self, *, system: str, user: str) -> str:
        raise RuntimeError("simulated provider failure")


@pytest.fixture
def store(tmp_path: Path) -> BrainStore:
    return BrainStore(tmp_path / "brain")


async def test_dream_cycle_returns_report_dataclass(store: BrainStore) -> None:
    page = LearnerPage(
        learner_id="l1",
        compiled_truth="Short initial truth.",
        timeline=[
            TimelineEntry(
                timestamp=datetime(2026, 4, 11, 14, 0, 0, tzinfo=UTC),
                kind="session_close",
                text="blocks=3 reteaches=1",
            )
        ],
    )
    store.put(page, "l1")
    report = await dream_cycle(
        "l1",
        _StaticConsolidator("A" * 500),
        store,
    )
    assert isinstance(report, DreamReport)
    assert report.pages_rewritten == 1
    assert report.pages_skipped == 0
    assert report.errors == 0
    assert report.duration_ms >= 0.0


async def test_dream_cycle_with_empty_brain_produces_zero_rewrites(
    store: BrainStore,
) -> None:
    report = await dream_cycle(
        "ghost",
        _StaticConsolidator("never called"),
        store,
    )
    assert report.pages_rewritten == 0
    assert report.pages_skipped == 0
    assert report.errors == 0


async def test_dream_cycle_skips_pages_with_empty_timeline(
    store: BrainStore,
) -> None:
    # No timeline entries → skipped without calling the consolidator.
    page = ConceptPage(
        learner_id="l1",
        concept_id="civil_war",
        compiled_truth="initial",
    )
    store.put(page, "l1")
    report = await dream_cycle(
        "l1",
        _StaticConsolidator("A" * 500),
        store,
    )
    assert report.pages_rewritten == 0
    assert report.pages_skipped == 1


async def test_dream_cycle_handles_provider_error(store: BrainStore) -> None:
    page = LearnerPage(
        learner_id="l1",
        compiled_truth="seed",
        timeline=[
            TimelineEntry(
                timestamp=datetime(2026, 4, 11, 14, 0, 0, tzinfo=UTC),
                kind="session_close",
                text="x",
            )
        ],
    )
    store.put(page, "l1")
    report = await dream_cycle("l1", _FailingConsolidator(), store)
    assert report.pages_rewritten == 0
    assert report.errors == 1


async def test_dream_cycle_is_idempotent_on_second_run(
    store: BrainStore,
) -> None:
    """First run rewrites; second run sees the already-matching compiled
    truth and skips."""
    static = "X" * 800
    page = LearnerPage(
        learner_id="l1",
        compiled_truth="old short",
        timeline=[
            TimelineEntry(
                timestamp=datetime(2026, 4, 11, 14, 0, 0, tzinfo=UTC),
                kind="session_close",
                text="x",
            )
        ],
    )
    store.put(page, "l1")
    consolidator = _StaticConsolidator(static)
    first = await dream_cycle("l1", consolidator, store)
    assert first.pages_rewritten == 1
    # Second run: compiled truth now equals the consolidator output,
    # so `_is_meaningful_change` returns False and the page is skipped.
    second = await dream_cycle("l1", consolidator, store)
    assert second.pages_rewritten == 0
    assert second.pages_skipped >= 1

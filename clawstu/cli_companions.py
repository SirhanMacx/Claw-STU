"""Phase 8 Part 2B companion commands -- ``wiki``, ``progress``,
``history``, ``review``, ``ask``, and real ``profile export/import``.

Each command shares a common shape:

1. Build a :class:`StoreBundle` via :func:`cli_state.default_stores`,
   which seeds an :class:`InMemoryPersistentStore` from a JSON
   snapshot on disk.
2. Resolve ``--learner``. If the caller omitted it, call
   :func:`cli_state.most_recent_learner` to pick the learner with the
   newest session, and raise a typer.Exit(1) with a friendly
   ``no learners yet`` message if the store is empty.
3. Render output via Rich -- markdown for wiki/ask, tables for
   progress/history/review, panels for headers.

Commands are intentionally keep read-only where possible -- they do
NOT rewrite the state file, because their view of the world is a
strict subset of what's already there. ``profile import`` and the
Part 2A ``learn``/``resume`` commands are the only write surfaces.

Layering: cli_companions sits in the ``_cli`` layer and imports from
memory, persistence, orchestrator, safety, curriculum, assessment,
and the sibling ``cli_state`` module. It does NOT import from
``cli`` or ``cli_chat`` -- the command wiring lives in ``cli.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from clawstu.cli_state import (
    NoLearnersError,
    StoreBundle,
    default_stores,
    most_recent_learner,
)
from clawstu.memory.wiki import generate_concept_wiki
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.profile.model import (
    Domain,
    EventKind,
    LearnerProfile,
    Modality,
    ModalityOutcome,
    ObservationEvent,
    ZPDEstimate,
)

_NO_LEARNERS_MESSAGE = (
    "no learners yet — run `clawstu learn` to start your first session."
)

_SPACED_REVIEW_CUTOFF_DAYS = 7


@dataclass(frozen=True)
class _ResolvedLearner:
    """A resolved (learner_id, rehydrated_profile) pair.

    The profile is a fresh :class:`LearnerProfile` stitched together
    from every substore so the command rendering can pull
    ``zpd_by_domain``, ``modality_outcomes``, ``misconceptions``, and
    ``events`` from a single object. This is the same rehydration
    pattern :class:`clawstu.api.state.AppState.get` uses.
    """

    learner_id: str
    profile: LearnerProfile


@dataclass(frozen=True)
class _ReviewRow:
    """One row in the ``clawstu review`` table.

    Using a dataclass instead of a raw dict keeps mypy happy -- the
    dict shape would have to be ``dict[str, str | int]`` which then
    fails the Table.add_row signature, and the per-field union
    signaling is exactly what we'd lose by flattening to strings.
    """

    concept: str
    last_seen: str
    days_ago: int
    domain: str


def _render_console() -> Console:
    """Return a fresh Rich :class:`Console`.

    Every command builds its own console so the tests can capture
    output via ``CliRunner`` without worrying about shared state.
    The real chat loop uses its own ``_RichChatIO`` indirection; this
    module's commands don't need that plumbing because they never
    prompt the student.
    """
    return Console()


def _resolve_learner(
    store: InMemoryPersistentStore, learner_id: str | None,
) -> _ResolvedLearner:
    """Resolve the effective learner id and rehydrate its profile.

    If ``learner_id`` is None we fall through to
    :func:`most_recent_learner`. An unknown explicit id is reported
    as a clean exit (not a crash) -- the user typed a name that
    doesn't exist, that's fine, we tell them.
    """
    if learner_id is None:
        try:
            resolved_id = most_recent_learner(store)
        except NoLearnersError as exc:
            typer.secho(_NO_LEARNERS_MESSAGE, fg=typer.colors.YELLOW)
            raise typer.Exit(code=1) from exc
    else:
        resolved_id = learner_id

    profile = store.learners.get(resolved_id)
    if profile is None:
        typer.secho(
            f"no learner named {resolved_id!r}. "
            "Run `clawstu learn --learner <name>` to start one.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)

    # Rehydrate substores onto the profile so the render helpers can
    # use the single-object pattern the chat loop uses.
    profile.zpd_by_domain = store.zpd.get_all(resolved_id)
    profile.modality_outcomes = store.modality_outcomes.get_all(resolved_id)
    profile.misconceptions = store.misconceptions.get_all(resolved_id)
    profile.events = store.events.list_for_learner(resolved_id)
    return _ResolvedLearner(learner_id=resolved_id, profile=profile)


# ---------------------------------------------------------------------------
# wiki
# ---------------------------------------------------------------------------


def run_wiki(concept: str, learner_id: str | None) -> None:
    """Implement ``clawstu wiki CONCEPT [--learner ID]``.

    Resolves the learner, calls
    :func:`clawstu.memory.wiki.generate_concept_wiki`, and renders
    the resulting markdown via ``rich.markdown.Markdown`` wrapped in
    a panel. If the brain has never written a concept page for this
    learner / concept pair, the wiki generator still returns a
    placeholder markdown body ("_(no concept page for this student
    yet)_"); we render that verbatim rather than adding another "no
    data" branch.
    """
    bundle = default_stores()
    resolved = _resolve_learner(bundle.persistence, learner_id)
    console = _render_console()

    markdown_text = generate_concept_wiki(
        learner_id=resolved.learner_id,
        concept=concept,
        brain_store=bundle.brain_store,
        kg_store=bundle.persistence.kg,
    )
    console.print(
        Panel(
            Markdown(markdown_text),
            title=(
                f"Wiki · {resolved.learner_id} · {concept}"
            ),
            border_style="blue",
            box=box.SIMPLE_HEAVY,
        )
    )


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------


def run_progress(learner_id: str | None) -> None:
    """Implement ``clawstu progress [--learner ID]``.

    Renders a header panel plus three Rich tables: ZPD per domain,
    modality outcomes, and top misconceptions. Every table shows an
    empty-state row ("no data yet") when the learner has nothing in
    that substore, so the command never crashes on a fresh learner.
    """
    bundle = default_stores()
    resolved = _resolve_learner(bundle.persistence, learner_id)
    profile = resolved.profile
    console = _render_console()

    sessions = bundle.persistence.sessions.list_for_learner(
        resolved.learner_id,
    )
    _render_progress_header(console, resolved.learner_id, profile, sessions)
    _render_zpd_table(console, profile.zpd_by_domain)
    _render_modality_table(console, profile.modality_outcomes)
    _render_session_count(console, sessions)
    _render_misconceptions(console, profile.misconceptions)


def _render_progress_header(
    console: Console,
    learner_id: str,
    profile: LearnerProfile,
    sessions: list[Any],
) -> None:
    del sessions  # currently summarized in a dedicated section below
    header = (
        f"Learner: [bold]{learner_id}[/bold]  ·  "
        f"Age bracket: {profile.age_bracket.value}  ·  "
        f"Created: {profile.created_at.strftime('%Y-%m-%d')}"
    )
    console.print(
        Panel(header, border_style="blue", box=box.SIMPLE_HEAVY),
    )


def _render_zpd_table(
    console: Console, zpd_by_domain: dict[Domain, ZPDEstimate],
) -> None:
    table = Table(
        title="ZPD by domain",
        box=box.SIMPLE_HEAVY,
        title_style="bold",
    )
    table.add_column("Domain")
    table.add_column("Tier")
    table.add_column("Confidence", justify="right")
    table.add_column("Samples", justify="right")
    table.add_column("Last updated")
    if not zpd_by_domain:
        table.add_row("—", "—", "—", "—", "no data yet")
    else:
        for domain in sorted(zpd_by_domain, key=lambda d: d.value):
            estimate = zpd_by_domain[domain]
            table.add_row(
                domain.value,
                estimate.tier.value,
                f"{estimate.confidence:.2f}",
                str(estimate.samples),
                estimate.last_updated.strftime("%Y-%m-%d %H:%M"),
            )
    console.print(table)


def _render_modality_table(
    console: Console,
    modality_outcomes: dict[Modality, ModalityOutcome],
) -> None:
    table = Table(
        title="Modality outcomes",
        box=box.SIMPLE_HEAVY,
        title_style="bold",
    )
    table.add_column("Modality")
    table.add_column("Attempts", justify="right")
    table.add_column("Successes", justify="right")
    table.add_column("Success rate", justify="right")
    table.add_column("Mean latency", justify="right")

    populated = {
        m: o for m, o in modality_outcomes.items() if o.attempts > 0
    }
    if not populated:
        table.add_row("—", "—", "—", "—", "no data yet")
    else:
        for modality in sorted(populated, key=lambda m: m.value):
            outcome = populated[modality]
            table.add_row(
                modality.value,
                str(outcome.attempts),
                str(outcome.successes),
                f"{outcome.success_rate:.0%}",
                f"{outcome.mean_latency:.1f}s",
            )
    console.print(table)


def _render_session_count(
    console: Console, sessions: list[Any],
) -> None:
    total = len(sessions)
    closed = sum(1 for s in sessions if str(s.phase) == "SessionPhase.CLOSED")
    if sessions:
        latest = max(sessions, key=lambda s: s.started_at)
        last_line = (
            f"Last session: {latest.started_at.strftime('%Y-%m-%d %H:%M')}"
        )
    else:
        last_line = "Last session: no sessions yet"

    panel = Panel(
        f"Total sessions: {total}\n"
        f"Closed sessions: {closed}\n"
        f"{last_line}",
        title="Sessions",
        border_style="blue",
        box=box.SIMPLE_HEAVY,
    )
    console.print(panel)


def _render_misconceptions(
    console: Console, misconceptions: dict[str, int],
) -> None:
    table = Table(
        title="Top misconceptions",
        box=box.SIMPLE_HEAVY,
        title_style="bold",
    )
    table.add_column("Concept")
    table.add_column("Count", justify="right")
    if not misconceptions:
        table.add_row("—", "no data yet")
    else:
        ordered = sorted(
            misconceptions.items(), key=lambda kv: (-kv[1], kv[0]),
        )
        for concept, count in ordered[:5]:
            table.add_row(concept, str(count))
    console.print(table)


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


def run_history(learner_id: str | None, limit: int) -> None:
    """Implement ``clawstu history [--learner ID] [--limit N]``.

    Lists the learner's past sessions in descending start-time order,
    truncated to ``limit`` rows. Empty state renders a friendly
    "no sessions yet" line pointing the student at ``clawstu learn``.
    """
    bundle = default_stores()
    resolved = _resolve_learner(bundle.persistence, learner_id)
    sessions = bundle.persistence.sessions.list_for_learner(
        resolved.learner_id,
    )
    sessions.sort(key=lambda s: s.started_at, reverse=True)
    sessions = sessions[:limit]

    console = _render_console()
    if not sessions:
        console.print(
            Panel(
                "No sessions yet. Run `clawstu learn` to start.",
                title=f"History · {resolved.learner_id}",
                border_style="yellow",
                box=box.SIMPLE_HEAVY,
            )
        )
        return

    table = Table(
        title=f"History · {resolved.learner_id}",
        box=box.SIMPLE_HEAVY,
        title_style="bold",
    )
    table.add_column("Started")
    table.add_column("Domain")
    table.add_column("Topic")
    table.add_column("Phase")
    table.add_column("Duration (min)", justify="right")
    table.add_column("Session ID")
    for session in sessions:
        started = session.started_at.strftime("%Y-%m-%d %H:%M")
        topic = session.topic or "—"
        duration = _session_duration_minutes(session)
        table.add_row(
            started,
            session.domain.value,
            topic,
            session.phase.value,
            str(duration),
            session.id[:8],
        )
    console.print(table)


def _session_duration_minutes(session: Any) -> int:
    """Return an integer minute count for a session.

    Sessions don't persist a ``closed_at`` field, so we approximate
    the duration as ``now - started_at`` for sessions that are still
    open, and ``1`` minute for sessions that have no elapsed time
    at all. The history table is a human-readable summary, not a
    timing audit, so a 1-minute floor is good enough.
    """
    now = datetime.now(UTC)
    started = session.started_at
    minutes = int((now - started).total_seconds() // 60)
    return max(1, minutes)


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------


def run_review(learner_id: str | None) -> None:
    """Implement ``clawstu review [--learner ID]``.

    Walks the learner's event log, collects the most recent timestamp
    for each concept, and flags concepts whose last review is older
    than :data:`_SPACED_REVIEW_CUTOFF_DAYS` days. Mirrors the logic
    in :mod:`clawstu.api.learners._count_pending_reviews` (which ships
    the exact same 7-day cutoff).
    """
    bundle = default_stores()
    resolved = _resolve_learner(bundle.persistence, learner_id)
    events = bundle.persistence.events.list_for_learner(resolved.learner_id)

    due = _concepts_due_for_review(events)
    console = _render_console()
    if not due:
        console.print(
            Panel(
                "Nothing due yet. Keep learning and come back in a few days.",
                title=f"Review · {resolved.learner_id}",
                border_style="green",
                box=box.SIMPLE_HEAVY,
            )
        )
        return

    table = Table(
        title=f"Concepts due for review · {resolved.learner_id}",
        box=box.SIMPLE_HEAVY,
        title_style="bold",
    )
    table.add_column("Concept")
    table.add_column("Last seen")
    table.add_column("Days ago", justify="right")
    table.add_column("Domain")
    for row in due:
        table.add_row(
            row.concept,
            row.last_seen,
            str(row.days_ago),
            row.domain,
        )
    console.print(table)


def _concepts_due_for_review(
    events: list[ObservationEvent],
) -> list[_ReviewRow]:
    """Return concepts whose last review-relevant event is > 7 days ago.

    Walks the event stream once, keeping the most recent
    (timestamp, domain) per concept. Only CHECK_FOR_UNDERSTANDING and
    CALIBRATION_ANSWER events count -- session_start/close events
    do not mean the student worked through the material. The return
    format is a list of dicts (not a pydantic model) because Rich's
    table renderer just needs string-keyed access.
    """
    review_kinds = {
        EventKind.CHECK_FOR_UNDERSTANDING,
        EventKind.CALIBRATION_ANSWER,
    }
    latest: dict[str, tuple[datetime, str]] = {}
    for event in events:
        if event.kind not in review_kinds:
            continue
        if event.concept is None:
            continue
        prior = latest.get(event.concept)
        if prior is None or event.timestamp > prior[0]:
            latest[event.concept] = (event.timestamp, event.domain.value)

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=_SPACED_REVIEW_CUTOFF_DAYS)
    due_rows: list[tuple[int, _ReviewRow]] = []
    for concept, (ts, domain) in latest.items():
        if ts >= cutoff:
            continue
        days_ago = max(1, int((now - ts).total_seconds() // 86_400))
        due_rows.append(
            (
                days_ago,
                _ReviewRow(
                    concept=concept,
                    last_seen=ts.strftime("%Y-%m-%d %H:%M"),
                    days_ago=days_ago,
                    domain=domain,
                ),
            )
        )
    due_rows.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _days, row in due_rows]


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------

_OFFLINE_WARNING = (
    "\u26a0 Running in offline demo mode. "
    "Run `clawstu setup` to configure a real provider for real answers."
)


def run_ask(question: str, learner_id: str | None) -> None:
    """Implement ``clawstu ask QUESTION [--learner ID]``.

    One-shot Socratic question routed through
    :meth:`ReasoningChain.ask`. No session state is created or
    modified -- for a full adaptive teach-assess cycle, the student
    should use ``clawstu learn``.

    If no learner exists the question is answered as an anonymous
    query -- no memory injection, no brain context. If a learner
    IS resolved, we inject a short brain slice via
    :func:`build_learner_context` so the chain can adapt its answer
    to the student's level and history.
    """
    import asyncio

    from clawstu.api.main import build_providers
    from clawstu.memory.context import build_learner_context
    from clawstu.orchestrator.chain import ReasoningChain
    from clawstu.orchestrator.config import load_config
    from clawstu.orchestrator.router import ModelRouter
    from clawstu.orchestrator.task_kinds import TaskKind

    bundle = default_stores()
    console = _render_console()

    # Resolve the learner if possible; fall through to anonymous on
    # failure. We intentionally do NOT raise typer.Exit here -- a
    # question like ``clawstu ask "what is mitosis"`` should always
    # return an answer, even if the user has never run ``learn``.
    resolved: _ResolvedLearner | None = None
    if learner_id is not None:
        profile = bundle.persistence.learners.get(learner_id)
        if profile is not None:
            resolved = _ResolvedLearner(
                learner_id=learner_id, profile=profile,
            )
    elif any(True for _ in _iter_learner_ids(bundle.persistence)):
        try:
            resolved_id = most_recent_learner(bundle.persistence)
            profile = bundle.persistence.learners.get(resolved_id)
            if profile is not None:
                resolved = _ResolvedLearner(
                    learner_id=resolved_id, profile=profile,
                )
        except NoLearnersError:
            pass

    # Build the reasoning chain.
    cfg = load_config()
    providers = build_providers(cfg)
    router = ModelRouter(config=cfg, providers=providers)
    chain = ReasoningChain(router=router)

    # Check for echo/offline mode. The router resolves
    # SOCRATIC_DIALOGUE at construction time; if it landed on the
    # EchoProvider, we're in offline demo mode regardless of what
    # other providers happen to be in the dict.
    sd_provider, _sd_model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    if type(sd_provider).__name__ == "EchoProvider":
        console.print(
            Panel(
                _OFFLINE_WARNING,
                border_style="yellow",
            )
        )

    # Optionally inject learner context.
    effective_question = question
    if resolved is not None:
        context = build_learner_context(
            learner_id=resolved.learner_id,
            concept=question[:50],
            brain_store=bundle.brain_store,
            kg_store=bundle.persistence.kg,
            max_chars=2000,
        )
        if context.text.strip():
            effective_question = (
                f"<learner_context>\n{context.text}\n</learner_context>\n\n"
                f"{question}"
            )

    async def _ask_and_cleanup() -> str:
        """Run the chain and close provider transports when done.

        ``build_providers`` constructs an ``OllamaProvider`` that opens
        an ``httpx.AsyncClient``. If we let the event loop close with
        the transport still open, Python emits ``ResourceWarning:
        unclosed transport``, which fails under ``filterwarnings =
        "error"``. Explicit cleanup avoids that.
        """
        try:
            return await chain.ask(
                effective_question,
                task_kind=TaskKind.SOCRATIC_DIALOGUE,
            )
        finally:
            for provider in providers.values():
                client = getattr(provider, "_client", None)
                if client is not None and hasattr(client, "aclose"):
                    await client.aclose()

    answer = asyncio.run(_ask_and_cleanup())
    console.print(
        Panel(
            Markdown(answer),
            title="Stuart",
            border_style="blue",
            box=box.SIMPLE_HEAVY,
        )
    )


def _iter_learner_ids(
    store: InMemoryPersistentStore,
) -> list[str]:
    """List learner ids in the store.

    Minimal helper that pokes the private ``_rows`` on the learner
    store. Same pattern as ``cli_state._iter_learners`` but returns
    only the id list -- kept separate so ``run_ask`` doesn't import
    from ``cli_state._iter_learners`` (which is not exported).
    """
    raw: object = getattr(store.learners, "_rows", {})
    if not isinstance(raw, dict):
        return []
    return list(raw.keys())


# ---------------------------------------------------------------------------
# Shared helpers (exported for the tests)
# ---------------------------------------------------------------------------


def build_stores_for_tests() -> StoreBundle:
    """Re-export the default_stores helper under a test-friendly name.

    Kept so tests can call ``cli_companions.build_stores_for_tests()``
    without reaching into ``cli_state`` themselves -- one import
    surface, one seam to monkeypatch.
    """
    return default_stores()


__all__ = [
    "NoLearnersError",
    "build_stores_for_tests",
    "run_ask",
    "run_history",
    "run_progress",
    "run_review",
    "run_wiki",
]

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

from clawstu import __version__
from clawstu.cli_state import (
    NoLearnersError,
    StoreBundle,
    default_stores,
    most_recent_learner,
)
from clawstu.engagement.session import Session
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


# HEARTBEAT: single-responsibility, no natural seam
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


def _resolve_learner_for_ask(
    bundle: StoreBundle, learner_id: str | None,
) -> _ResolvedLearner | None:
    """Resolve the learner for ``clawstu ask``, returning None on miss.

    Unlike the strict ``_resolve_learner`` used by other companions,
    this helper never raises -- a question should always return an
    answer, even if the user has never run ``learn``.
    """
    if learner_id is not None:
        profile = bundle.persistence.learners.get(learner_id)
        if profile is not None:
            return _ResolvedLearner(learner_id=learner_id, profile=profile)
        return None

    if any(True for _ in _iter_learner_ids(bundle.persistence)):
        try:
            resolved_id = most_recent_learner(bundle.persistence)
            profile = bundle.persistence.learners.get(resolved_id)
            if profile is not None:
                return _ResolvedLearner(
                    learner_id=resolved_id, profile=profile,
                )
        except NoLearnersError:
            pass
    return None


def _build_ask_prompt(
    question: str,
    resolved: _ResolvedLearner | None,
    bundle: StoreBundle,
) -> str:
    """Optionally inject learner context into the question string.

    Returns the original question if no learner is resolved, or a
    ``<learner_context>``-wrapped version when brain context exists.
    """
    if resolved is None:
        return question

    from clawstu.memory.context import build_learner_context

    context = build_learner_context(
        learner_id=resolved.learner_id,
        concept=question[:50],
        brain_store=bundle.brain_store,
        kg_store=bundle.persistence.kg,
        max_chars=2000,
    )
    if context.text.strip():
        return (
            f"<learner_context>\n{context.text}\n</learner_context>\n\n"
            f"{question}"
        )
    return question


def _execute_ask(
    effective_question: str,
    chain: Any,
    providers: dict[str, Any],
) -> str:
    """Run the chain synchronously and return the answer string.

    Closes provider transports after the call to avoid
    ``ResourceWarning`` under ``filterwarnings = "error"``.
    Raises ``ProviderError`` on failure.
    """
    import asyncio

    from clawstu.orchestrator.task_kinds import TaskKind

    async def _ask_and_cleanup() -> str:
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

    return asyncio.run(_ask_and_cleanup())


def run_ask(question: str, learner_id: str | None) -> None:
    """Implement ``clawstu ask QUESTION [--learner ID]``.

    One-shot Socratic question routed through
    :meth:`ReasoningChain.ask`. No session state is created or
    modified -- for a full adaptive teach-assess cycle, the student
    should use ``clawstu learn``.
    """
    from clawstu.api.main import build_providers
    from clawstu.orchestrator.chain import ReasoningChain
    from clawstu.orchestrator.config import load_config
    from clawstu.orchestrator.providers import ProviderError
    from clawstu.orchestrator.router import ModelRouter
    from clawstu.orchestrator.task_kinds import TaskKind

    bundle = default_stores()
    console = _render_console()
    resolved = _resolve_learner_for_ask(bundle, learner_id)

    cfg = load_config()
    providers = build_providers(cfg)
    router = ModelRouter(config=cfg, providers=providers)
    chain = ReasoningChain(router=router)

    sd_provider, _sd_model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    if type(sd_provider).__name__ == "EchoProvider":
        console.print(Panel(_OFFLINE_WARNING, border_style="yellow"))

    effective_question = _build_ask_prompt(question, resolved, bundle)

    try:
        answer = _execute_ask(effective_question, chain, providers)
    except ProviderError as exc:
        console.print(
            Panel(
                f"Provider error: {exc}\n\n"
                "Tip: run `clawstu doctor --ping` to check provider "
                "reachability, or `clawstu setup` to reconfigure.",
                title="Stuart",
                border_style="red",
            )
        )
        raise typer.Exit(code=1) from None
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

    Uses the public ``list_all`` method on the learner store when
    available, falling back to ``_rows`` for older store versions.
    """
    if hasattr(store.learners, "list_all"):
        return [p.learner_id for p in store.learners.list_all()]
    raw: object = getattr(store.learners, "_rows", {})
    if not isinstance(raw, dict):
        return []
    return list(raw.keys())


# ---------------------------------------------------------------------------
# profile export / import
# ---------------------------------------------------------------------------

_EXPORT_SCHEMA_VERSION = 1


def _collect_export_artifacts(
    bundle: StoreBundle,
    resolved: _ResolvedLearner,
    staging: Any,
) -> None:
    """Stage all export files into ``staging`` directory.

    Writes profile.json, sessions.jsonl, events.jsonl, brain/,
    and meta.json into the staging directory for tarball creation.
    """
    import json as _json
    import shutil

    profile = resolved.profile

    (staging / "profile.json").write_text(
        profile.model_dump_json(indent=2), encoding="utf-8",
    )

    sessions = bundle.persistence.sessions.list_for_learner(
        resolved.learner_id,
    )
    with (staging / "sessions.jsonl").open("w", encoding="utf-8") as fh:
        for session in sessions:
            fh.write(session.model_dump_json())
            fh.write("\n")

    events_raw = _iter_events_for_export(
        bundle.persistence, resolved.learner_id,
    )
    with (staging / "events.jsonl").open("w", encoding="utf-8") as fh:
        for envelope in events_raw:
            fh.write(_json.dumps(envelope))
            fh.write("\n")

    from clawstu.memory.store import _learner_hash

    brain_subdir = (
        bundle.brain_store.base_dir / _learner_hash(resolved.learner_id)
    )
    brain_dest = staging / "brain"
    if brain_subdir.exists():
        shutil.copytree(brain_subdir, brain_dest)
    else:
        brain_dest.mkdir()

    meta = {
        "schema_version": _EXPORT_SCHEMA_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "learner_id": resolved.learner_id,
        "clawstu_version": __version__,
    }
    (staging / "meta.json").write_text(
        _json.dumps(meta, indent=2), encoding="utf-8",
    )


def _write_export_tarball(staging: Any, out_path: Any) -> None:
    """Create a ``.tar.gz`` from the staged directory."""
    import tarfile

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(out_path), "w:gz") as tar:
        for entry in sorted(staging.rglob("*")):
            arcname = str(entry.relative_to(staging))
            tar.add(str(entry), arcname=arcname)


def run_profile_export(
    learner_id: str, out: str, *, force: bool = False,
) -> None:
    """Implement ``clawstu profile export LEARNER_ID --out PATH``.

    Creates a ``.tar.gz`` tarball containing profile, sessions,
    events, brain pages, and export metadata.
    """
    import tempfile
    from pathlib import Path as _Path

    out_path = _Path(out)
    if out_path.exists() and not force:
        typer.secho(
            f"file already exists: {out_path}. "
            "Pass --force to overwrite.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    bundle = default_stores()
    resolved = _resolve_learner(bundle.persistence, learner_id)

    with tempfile.TemporaryDirectory() as td:
        staging = _Path(td)
        _collect_export_artifacts(bundle, resolved, staging)
        _write_export_tarball(staging, out_path)

    size = out_path.stat().st_size
    typer.echo(f"\u2713 Exported to {out_path} ({size} bytes)")


def run_profile_import(
    path: str, *, overwrite: bool = False,
) -> None:
    """Implement ``clawstu profile import PATH [--overwrite]``.

    Reads a tarball created by ``profile export``, validates the
    ``meta.json`` schema, deserializes the profile + sessions + events,
    upserts everything into persistence, and copies the brain/
    directory back into the :class:`BrainStore`.
    """
    import tempfile
    from pathlib import Path as _Path

    from clawstu.cli_state import save_persistence_to_disk

    source = _Path(path)
    _validate_import_source(source)

    with tempfile.TemporaryDirectory() as td:
        extract_dir = _Path(td) / "extracted"
        extract_dir.mkdir()
        _extract_tar_safely(source, extract_dir)
        _validate_import_meta(extract_dir)
        profile = _deserialize_import_profile(extract_dir)
        learner_id = profile.learner_id

        bundle = default_stores()
        _check_learner_conflict(bundle, learner_id, overwrite)
        bundle.persistence.learners.upsert(profile)

        session_count = _import_sessions(extract_dir, bundle)
        event_count = _import_events(extract_dir, bundle, learner_id)
        _import_brain_directory(extract_dir, bundle, learner_id)

        save_persistence_to_disk(
            bundle.persistence, bundle.state_path,
        )

    typer.echo(
        f"\u2713 Imported learner {learner_id!r} with "
        f"{session_count} sessions and {event_count} events."
    )


def _validate_import_source(source: Any) -> None:
    """Validate that the import source path exists and is a tarball."""
    import tarfile

    if not source.exists():
        typer.secho(f"file not found: {source}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if not tarfile.is_tarfile(str(source)):
        typer.secho(f"not a tarball: {source}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


def _extract_tar_safely(source: Any, extract_dir: Any) -> None:
    """Extract tarball with zip-bomb and path-traversal protections."""
    import tarfile
    from pathlib import Path as _Path

    _TAR_MAX_MEMBERS = 1000
    _TAR_MAX_TOTAL_SIZE = 100 * 1024 * 1024  # 100MB

    with tarfile.open(str(source), "r:gz") as tar:
        members = tar.getmembers()

        if len(members) > _TAR_MAX_MEMBERS:
            typer.secho(
                f"tarball has {len(members)} members "
                f"(max {_TAR_MAX_MEMBERS})",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)

        total_size = 0
        for member in members:
            member_path = _Path(member.name)
            if member.name.startswith("/") or ".." in member_path.parts:
                typer.secho(
                    f"tarball contains unsafe path: {member.name!r}",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(code=1)
            resolved = (extract_dir / member.name).resolve()
            if not str(resolved).startswith(str(extract_dir.resolve())):
                typer.secho(
                    f"tarball path escapes target: {member.name!r}",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(code=1)
            total_size += member.size

        if total_size > _TAR_MAX_TOTAL_SIZE:
            typer.secho(
                f"tarball total extracted size {total_size} bytes "
                f"exceeds max {_TAR_MAX_TOTAL_SIZE} bytes (100MB)",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)

        tar.extractall(path=str(extract_dir), filter="data")


def _validate_import_meta(extract_dir: Any) -> None:
    """Validate the meta.json schema version inside the extracted tarball."""
    import json as _json

    meta_path = extract_dir / "meta.json"
    if not meta_path.exists():
        typer.secho("tarball missing meta.json", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    meta = _json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("schema_version") != _EXPORT_SCHEMA_VERSION:
        typer.secho(
            f"unsupported schema_version: {meta.get('schema_version')}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)


def _deserialize_import_profile(extract_dir: Any) -> LearnerProfile:
    """Deserialize and return the LearnerProfile from the extracted tarball."""
    profile_path = extract_dir / "profile.json"
    if not profile_path.exists():
        typer.secho("tarball missing profile.json", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    return LearnerProfile.model_validate_json(
        profile_path.read_text(encoding="utf-8"),
    )


def _check_learner_conflict(
    bundle: StoreBundle, learner_id: str, overwrite: bool,
) -> None:
    """Raise typer.Exit if the learner already exists and overwrite is False."""
    if (
        bundle.persistence.learners.get(learner_id) is not None
        and not overwrite
    ):
        typer.secho(
            f"learner {learner_id!r} already exists. "
            "Pass --overwrite to replace.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)


def _import_sessions(extract_dir: Any, bundle: StoreBundle) -> int:
    """Import sessions from the extracted sessions.jsonl file."""
    sessions_path = extract_dir / "sessions.jsonl"
    session_count = 0
    if sessions_path.exists():
        for line in sessions_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            session = Session.model_validate_json(line)
            bundle.persistence.sessions.upsert(session)
            session_count += 1
    return session_count


def _import_events(
    extract_dir: Any, bundle: StoreBundle, learner_id: str,
) -> int:
    """Import observation events from the extracted events.jsonl file."""
    import json as _json

    events_path = extract_dir / "events.jsonl"
    event_count = 0
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            envelope = _json.loads(line)
            event = ObservationEvent.model_validate(envelope.get("event", {}))
            session_id = envelope.get("session_id")
            resolved_sid: str | None = (
                session_id if isinstance(session_id, str) else None
            )
            bundle.persistence.events.append(
                event,
                learner_id=learner_id,
                session_id=resolved_sid,
            )
            event_count += 1
    return event_count


def _import_brain_directory(
    extract_dir: Any, bundle: StoreBundle, learner_id: str,
) -> None:
    """Copy the brain/ directory from the extracted tarball into BrainStore."""
    import shutil

    from clawstu.memory.store import _learner_hash

    brain_src = extract_dir / "brain"
    if brain_src.exists() and any(brain_src.iterdir()):
        brain_dest = (
            bundle.brain_store.base_dir / _learner_hash(learner_id)
        )
        if brain_dest.exists():
            shutil.rmtree(brain_dest)
        shutil.copytree(brain_src, brain_dest)


def _iter_events_for_export(
    persistence: InMemoryPersistentStore, learner_id: str,
) -> list[dict[str, object]]:
    """Return events as envelope dicts for JSONL serialization.

    Uses the public ``list_for_learner`` API when available to avoid
    accessing private store attributes.
    """
    events = persistence.events.list_for_learner(learner_id)
    out: list[dict[str, object]] = []
    for event in events:
        out.append(
            {
                "learner_id": learner_id,
                "session_id": None,
                "event": event.model_dump(mode="json"),
            }
        )
    return out


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
    "run_profile_export",
    "run_profile_import",
    "run_progress",
    "run_review",
    "run_wiki",
]

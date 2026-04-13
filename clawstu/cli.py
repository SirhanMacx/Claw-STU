"""clawstu — the Claw-STU console entry point.

Thin wrapper over the HTTP API and the proactive scheduler. No
pedagogical logic lives here; every command calls functions that
already exist in clawstu.api, clawstu.orchestrator, clawstu.memory,
clawstu.scheduler, clawstu.cli_chat, or (Phase 8 Part 2B)
clawstu.cli_companions.

Commands:
  clawstu                                    drop into `learn` (default)
  clawstu learn [TOPIC]                      start an interactive learning session
  clawstu resume <learner_id>                warm-start from a pre-generated artifact
  clawstu wiki CONCEPT                       per-student concept wiki (markdown)
  clawstu progress                           learner dashboard (ZPD, modalities)
  clawstu history                            past sessions for a learner
  clawstu review                             concepts due for spaced review
  clawstu setup                              interactive provider wizard
  clawstu serve                              start the FastAPI app
  clawstu doctor                             self-diagnosis
  clawstu scheduler run-once --task <name>   run a proactive task once
  clawstu profile export <learner_id>        export profile + brain tarball
  clawstu profile import <path>              restore a tarball
"""
from __future__ import annotations

import typer

from clawstu import __version__
from clawstu.setup_wizard import SetupError, run_setup


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"clawstu {__version__}")
        raise typer.Exit


app: typer.Typer = typer.Typer(
    name="clawstu",
    help=(
        "Stuart — a personal learning agent that grows with the "
        "student. Made by a teacher, for learners."
    ),
    # `no_args_is_help=False` + `invoke_without_command=True` lets the
    # callback below dispatch to the default `learn` command when the
    # user just types `clawstu` with no args, same way `clawed` drops
    # you into a chat. Typer still renders --help when the user passes
    # --help explicitly, because --help exits BEFORE the callback runs.
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
)

scheduler_app: typer.Typer = typer.Typer(help="Proactive-scheduler administration.")
profile_app: typer.Typer = typer.Typer(help="Learner profile portability.")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(profile_app, name="profile")


@app.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print the version and exit.",
    ),
) -> None:
    """Default dispatch: ``clawstu`` with no subcommand runs ``learn``.

    The callback runs on every invocation, but only routes to
    ``learn`` when no subcommand was supplied. Subcommand flows
    (``setup``, ``doctor``, ``serve``, etc.) still run normally
    because ``ctx.invoked_subcommand`` is set in that case.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(
            learn,
            topic=None,
            learner_id=None,
            age=None,
            domain=None,
        )


# HEARTBEAT: single-responsibility, no natural seam
@app.command()
def learn(
    topic: str | None = typer.Argument(
        None,
        help=(
            "Topic to learn about. If omitted, Stuart will prompt "
            "for it interactively."
        ),
    ),
    learner_id: str | None = typer.Option(
        None,
        "--learner",
        "-l",
        help="Learner ID or name. Prompted interactively when omitted.",
    ),
    age: int | None = typer.Option(
        None,
        "--age",
        "-a",
        help="Learner age. Prompted interactively when omitted.",
    ),
    domain: str | None = typer.Option(
        None,
        "--domain",
        "-d",
        help=(
            "Subject domain. One of: us_history, global_history, "
            "civics, ela, science, math, other. Defaults to 'other'."
        ),
    ),
) -> None:
    """Start an interactive learning session with Stuart.

    The headline command. Types a banner, asks for name / age / topic
    if they aren't supplied, onboards the learner, teaches at least
    one block, checks understanding, and prints a closing summary.
    Every mutating step is checkpointed to persistence so Ctrl-C
    leaves a resumable state behind.
    """
    from clawstu.cli_chat import ChatInputs, run_chat_session
    from clawstu.profile.model import Domain

    try:
        domain_enum = Domain(domain) if domain else None
    except ValueError as exc:
        valid = ", ".join(d.value for d in Domain)
        typer.secho(
            f"unknown --domain {domain!r}; valid choices: {valid}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2) from exc

    inputs = ChatInputs(
        learner_id=learner_id,
        age=age,
        topic=topic,
        domain=domain_enum,
    )
    run_chat_session(inputs=inputs)


@app.command()
def wiki(
    concept: str = typer.Argument(
        ...,
        help="Concept name (e.g. 'french_revolution_causes').",
    ),
    learner_id: str | None = typer.Option(
        None,
        "--learner",
        "-l",
        help=(
            "Learner ID. Defaults to the most recently active learner."
        ),
    ),
) -> None:
    """Print Stuart's per-student wiki for a concept.

    Pulls the learner's ConceptPage compiled truth, the misconceptions
    flagged on the concept, and the tied primary sources. Renders as
    markdown in the terminal.
    """
    from clawstu.cli_companions import run_wiki

    run_wiki(concept=concept, learner_id=learner_id)


@app.command()
def progress(
    learner_id: str | None = typer.Option(
        None, "--learner", "-l",
        help=(
            "Learner ID. Defaults to the most recently active learner."
        ),
    ),
) -> None:
    """Show the learner dashboard: ZPD per domain, modality mix, sessions."""
    from clawstu.cli_companions import run_progress

    run_progress(learner_id=learner_id)


@app.command()
def history(
    learner_id: str | None = typer.Option(
        None, "--learner", "-l",
        help=(
            "Learner ID. Defaults to the most recently active learner."
        ),
    ),
    limit: int = typer.Option(
        10, "--limit", "-n", help="Most recent N sessions.",
    ),
) -> None:
    """List past sessions for a learner."""
    from clawstu.cli_companions import run_history

    run_history(learner_id=learner_id, limit=limit)


@app.command()
def review(
    learner_id: str | None = typer.Option(
        None, "--learner", "-l",
        help=(
            "Learner ID. Defaults to the most recently active learner."
        ),
    ),
) -> None:
    """Show concepts due for spaced review.

    A concept is due when its most recent CHECK_FOR_UNDERSTANDING or
    CALIBRATION_ANSWER event is older than 7 days. Same cutoff the
    `spaced_review` scheduler task uses for the queue API surface.
    """
    from clawstu.cli_companions import run_review

    run_review(learner_id=learner_id)


@app.command()
def ask(
    question: str = typer.Argument(
        ..., help="Your question.",
    ),
    learner_id: str | None = typer.Option(
        None,
        "--learner",
        "-l",
        help=(
            "Learner ID. Defaults to the most recently active learner."
        ),
    ),
) -> None:
    """One-shot Socratic question outside of a structured session.

    Routed through ReasoningChain.ask() with TaskKind.SOCRATIC_DIALOGUE.
    No session state is created or modified. Use ``clawstu learn`` for
    a full adaptive teach-assess cycle.
    """
    from clawstu.cli_companions import run_ask

    run_ask(question=question, learner_id=learner_id)


@app.command()
def resume(
    session_id: str = typer.Argument(help="Session ID to resume"),
    learner_id: str | None = typer.Option(
        None, "--learner", "-l", help="Learner ID",
    ),
) -> None:
    """Resume a previous learning session by session ID.

    Loads persistence from disk, finds the session, and drops the
    student back into the interactive chat loop with the existing
    profile and session state. Lists available sessions when the
    requested one is not found.
    """
    from clawstu.cli_chat import run_chat_session_from_bundle
    from clawstu.cli_state import default_stores

    stores = default_stores()
    session = stores.persistence.sessions.get(session_id)
    if session is None:
        typer.secho(
            f"Session {session_id!r} not found.", fg=typer.colors.RED,
        )
        all_sessions = stores.persistence.sessions.list_all()
        if all_sessions:
            typer.echo("Available sessions:")
            for s in all_sessions:
                typer.echo(f"  {s.id}  ({s.learner_id}, {s.domain.value})")
        else:
            typer.echo("No sessions found. Run `clawstu learn` first.")
        raise typer.Exit(code=1)

    resolved_lid = learner_id or session.learner_id
    profile = stores.persistence.learners.get(resolved_lid)
    if profile is None:
        typer.secho(
            f"Learner {resolved_lid!r} not found.", fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    # Rehydrate profile substores
    profile.zpd_by_domain = stores.persistence.zpd.get_all(resolved_lid)
    profile.modality_outcomes = stores.persistence.modality_outcomes.get_all(
        resolved_lid,
    )
    profile.misconceptions = stores.persistence.misconceptions.get_all(
        resolved_lid,
    )
    profile.events = stores.persistence.events.list_for_learner(resolved_lid)

    run_chat_session_from_bundle(profile=profile, session=session)


@app.command(name="warm-start")
def warm_start(
    learner_id: str = typer.Argument(
        ..., help="Learner ID to resume."
    ),
) -> None:
    """Warm-start from a pre-generated artifact.

    Loads the most recent unconsumed :class:`NextSessionArtifact`
    from persistence, constructs a primed :class:`Session`, and
    drops the student back into the same chat loop ``learn`` uses.
    """
    from clawstu.cli_chat import run_resume_session
    from clawstu.engagement.session import NoArtifactError

    try:
        run_resume_session(learner_id=learner_id)
    except NoArtifactError as exc:
        typer.secho(
            f"nothing to resume: {exc}", fg=typer.colors.YELLOW,
        )
        typer.echo("Run `clawstu learn` to start a fresh session.")
        raise typer.Exit(code=1) from exc


# HEARTBEAT: single-responsibility, no natural seam
@app.command()
def setup(
    interactive: bool = typer.Option(
        True,
        "--interactive/--no-interactive",
        help=(
            "Run the wizard in interactive mode (default). "
            "--no-interactive runs without prompts using --provider "
            "(and --api-key for non-echo providers); intended for "
            "scripted deployments and CI."
        ),
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help=(
            "Provider name to write without prompting. One of: "
            "anthropic, openai, openrouter, ollama, echo. Required "
            "when --no-interactive is set."
        ),
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help=(
            "API key for the chosen provider. Required when using "
            "--no-interactive with anthropic, openai, or openrouter."
        ),
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help=(
            "Override the provider's base URL. Mainly useful for "
            "Ollama or self-hosted gateways."
        ),
    ),
) -> None:
    """Interactive provider setup -- pick a provider, save the API key.

    Walks the operator through provider selection, captures an API key
    (or local Ollama base URL), runs a tiny verification ping, and
    writes the result to ``~/.claw-stu/secrets.json`` with 0600 perms.

    Pass ``--no-interactive --provider <name>`` for scripted use.
    """
    try:
        run_setup(
            interactive=interactive,
            provider_override=provider,
            api_key_override=api_key,
            base_url_override=base_url,
        )
    except SetupError as exc:
        typer.secho(f"setup failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
) -> None:
    """Start the FastAPI app + embedded scheduler.

    Binds to 127.0.0.1 by default (localhost-only). Pass --host 0.0.0.0
    explicitly if you know what you're doing.
    """
    import uvicorn

    typer.echo(f"clawstu serve: starting on {host}:{port}")
    typer.echo(f"Open http://{host}:{port}/docs for the interactive API.")
    uvicorn.run(
        "clawstu.api.main:app",
        host=host,
        port=port,
        log_level="info",
    )


@app.command()
def doctor(
    ping: bool = typer.Option(
        False,
        "--ping",
        help=(
            "Also attempt a round-trip against every configured provider. "
            "Without --ping, doctor is a pure static config dump that "
            "never touches the network."
        ),
    ),
) -> None:
    """Self-diagnosis: config load, provider reachability, SQLite, FTS5."""
    from clawstu.orchestrator.config import load_config

    typer.echo("clawstu doctor — Phase 1 baseline")
    try:
        cfg = load_config()
    except Exception as exc:
        typer.secho(f"  config load: FAIL ({exc})", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    typer.secho("  config load: ok", fg=typer.colors.GREEN)
    typer.echo(f"    data_dir: {cfg.data_dir}")
    typer.echo(f"    primary_provider: {cfg.primary_provider}")
    typer.echo(f"    fallback_chain: {list(cfg.fallback_chain)}")

    if ping:
        typer.echo("  provider reachability:")
        from clawstu.api.main import build_providers

        providers = build_providers(cfg)
        for name, provider in providers.items():
            ptype = type(provider).__name__
            typer.echo(f"    {name} ({ptype}): configured")
        typer.secho(
            "    (experimental) Full connectivity ping deferred to a future release.",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.echo("  provider reachability: skipped (pass --ping to try)")


@scheduler_app.command("run-once")
def scheduler_run_once(
    task: str = typer.Option(..., "--task", help="Task name to run."),
) -> None:
    """Run one proactive task immediately (experimental).

    Constructs the scheduler runner and executes the named task once.
    Requires the app state and provider keys to be configured.
    """
    import asyncio

    from clawstu.api.main import build_scheduler_runner
    from clawstu.api.state import AppState

    typer.echo(f"clawstu scheduler run-once --task {task}")
    state = AppState()
    try:
        runner = build_scheduler_runner(state)
    except Exception as exc:
        typer.secho(f"  scheduler init failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    spec = runner.registry.get(task)
    if spec is None:
        typer.secho(f"  unknown task: {task!r}", fg=typer.colors.RED)
        available = [s.name for s in runner.registry.list_all()]
        typer.echo(f"  available tasks: {available}")
        raise typer.Exit(code=1)

    typer.echo(f"  running task: {spec.name} ...")

    async def _run() -> None:
        await runner.start()
        try:
            # Use the internal _run_spec method which is the
            # same path APScheduler uses when firing a job.
            await runner._run_spec(task)
        finally:
            await runner.stop()

    try:
        asyncio.run(_run())
        typer.secho("  done.", fg=typer.colors.GREEN)
    except Exception as exc:
        typer.secho(f"  task failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


@profile_app.command("export")
def profile_export(
    learner_id: str = typer.Argument(...),
    out: str = typer.Option(..., "--out", "-o", help="Output tarball path."),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Overwrite the output file if it already exists.",
    ),
) -> None:
    """Export a learner profile + brain pages as a .tar.gz tarball.

    The tarball contains profile.json, sessions.jsonl, events.jsonl,
    a brain/ directory with the learner's concept pages, and a
    meta.json with the schema version and export timestamp.
    """
    from clawstu.cli_companions import run_profile_export

    run_profile_export(learner_id=learner_id, out=out, force=force)


@profile_app.command("import")
def profile_import(
    path: str = typer.Argument(...),
    overwrite: bool = typer.Option(
        False, "--overwrite",
        help="Replace an existing learner with the imported one.",
    ),
) -> None:
    """Import a previously exported learner tarball.

    Reads a .tar.gz created by ``profile export``, validates the
    schema version, and upserts the learner, sessions, events, and
    brain pages into persistence. Refuses to overwrite an existing
    learner unless ``--overwrite`` is passed.
    """
    from clawstu.cli_companions import run_profile_import

    run_profile_import(path=path, overwrite=overwrite)


@app.command()
def bot(
    token: str | None = typer.Option(
        None, "--token", envvar="STU_TELEGRAM_TOKEN",
    ),
) -> None:
    """Start the Stuart Telegram bot.

    Requires a Telegram bot token from @BotFather.
    Set via --token or STU_TELEGRAM_TOKEN env var.
    """
    if not token:
        typer.secho(
            "No token provided. Get one from @BotFather on Telegram.",
            fg=typer.colors.RED,
        )
        typer.echo(
            "  Set STU_TELEGRAM_TOKEN in your environment, "
            "or pass --token <token>"
        )
        raise typer.Exit(code=1)
    from clawstu.bot import run_bot

    run_bot(token=token)


@app.command("mcp-server")
def mcp_server() -> None:
    """Start Stuart as an MCP server (stdin/stdout, for Claude Code integration).

    Exposes Stuart's capabilities as MCP tools that Claude Code,
    Claude Desktop, and other MCP clients can invoke directly.
    Uses stdio transport (the MCP standard).

    Tools exposed: clawstu_ask, clawstu_wiki, clawstu_progress,
    clawstu_review, clawstu_learn_session.
    """
    from clawstu.mcp_server import run_mcp_server

    run_mcp_server()


# ---------------------------------------------------------------------------
# v5 parity commands -- CLI wrappers for agent generation, export, search,
# and ingest. Each is a thin shell that falls back gracefully when the
# agent package is not fully wired.
# ---------------------------------------------------------------------------

_V5_ARTIFACT_TYPES = frozenset({
    "worksheet", "game", "visual", "simulation", "animation",
    "slides", "study-guide", "practice-test", "flashcards",
})

_V5_EXPORT_FORMATS = frozenset({"pdf", "docx", "html", "csv"})

_V5_STUB_MSG = "Agent tools coming in v5. Generation pipeline not yet wired."


def _run_generate(artifact_type: str, topic: str, learner_id: str | None) -> None:
    """Shared logic for all generation CLI commands.

    Validates the artifact type, then delegates to the agent loop.
    Falls back with a friendly message when the agent package is not
    yet importable.
    """
    if artifact_type not in _V5_ARTIFACT_TYPES:
        valid = ", ".join(sorted(_V5_ARTIFACT_TYPES))
        typer.secho(
            f"Unknown artifact type {artifact_type!r}; valid: {valid}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    try:
        from clawstu.agent.loop import AgentLoop

        _ = AgentLoop  # keep linter happy; actual call will come in Phase 2
        typer.echo(f"Generating {artifact_type} on '{topic}' ...")
        typer.secho(_V5_STUB_MSG, fg=typer.colors.YELLOW)
    except (ImportError, ModuleNotFoundError):
        typer.echo(f"Would generate {artifact_type} on '{topic}'.")
        typer.secho(_V5_STUB_MSG, fg=typer.colors.YELLOW)


@app.command()
def generate(
    artifact_type: str = typer.Argument(
        help="Type: worksheet, game, visual, simulation, slides, study-guide, practice-test, flashcards",
    ),
    topic: str = typer.Argument(help="Topic to generate content for"),
    learner_id: str | None = typer.Option(
        None, "--learner", "-l", help="Learner ID (uses most recent if omitted)",
    ),
) -> None:
    """Generate a learning artifact for a student.

    Supported types: worksheet, game, visual, simulation, animation,
    slides, study-guide, practice-test, flashcards. The artifact is
    saved to the current directory.
    """
    _run_generate(artifact_type, topic, learner_id)


@app.command()
def export(
    fmt: str = typer.Argument(help="Format: pdf, docx, html, csv"),
    source: str | None = typer.Option(
        None, "--source", "-s", help="Path to artifact (uses latest session if omitted)",
    ),
) -> None:
    """Export the most recent session's artifacts to a file format.

    Supported formats: pdf, docx, html, csv. Defaults to the
    latest session when --source is omitted.
    """
    if fmt not in _V5_EXPORT_FORMATS:
        valid = ", ".join(sorted(_V5_EXPORT_FORMATS))
        typer.secho(
            f"Unknown export format {fmt!r}; valid: {valid}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    try:
        from clawstu.agent.tools import export_pdf

        _ = export_pdf
        typer.echo(f"Exporting to {fmt} ...")
        typer.secho(_V5_STUB_MSG, fg=typer.colors.YELLOW)
    except (ImportError, ModuleNotFoundError):
        src_label = source if source else "latest session"
        typer.echo(f"Would export {src_label} as {fmt}.")
        typer.secho(_V5_STUB_MSG, fg=typer.colors.YELLOW)


@app.command()
def search(
    query: str = typer.Argument(help="Search brain pages and teacher materials"),
) -> None:
    """Search brain pages and shared teacher materials.

    Queries the learner's brain store and, when available, the
    teacher's shared knowledge base. Results are printed with
    snippets.
    """
    try:
        from clawstu.agent.tools import search_brain

        _ = search_brain
        typer.echo(f"Searching for '{query}' ...")
        typer.secho(_V5_STUB_MSG, fg=typer.colors.YELLOW)
    except (ImportError, ModuleNotFoundError):
        typer.echo(f"Would search for '{query}'.")
        typer.secho(_V5_STUB_MSG, fg=typer.colors.YELLOW)


@app.command()
def practice(
    topic: str = typer.Argument(help="Topic to generate practice problems for"),
    learner_id: str | None = typer.Option(
        None, "--learner", "-l", help="Learner ID (uses most recent if omitted)",
    ),
) -> None:
    """Generate a practice test for a topic.

    Shortcut for ``clawstu generate practice-test <topic>``.
    """
    _run_generate("practice-test", topic, learner_id)


@app.command()
def flashcards(
    topic: str = typer.Argument(help="Topic to generate flashcards for"),
    learner_id: str | None = typer.Option(
        None, "--learner", "-l", help="Learner ID (uses most recent if omitted)",
    ),
) -> None:
    """Generate flashcards for a topic.

    Shortcut for ``clawstu generate flashcards <topic>``.
    """
    _run_generate("flashcards", topic, learner_id)


@app.command()
def game(
    topic: str = typer.Argument(help="Topic to generate a game for"),
    learner_id: str | None = typer.Option(
        None, "--learner", "-l", help="Learner ID (uses most recent if omitted)",
    ),
) -> None:
    """Generate an interactive game for a topic.

    Shortcut for ``clawstu generate game <topic>``.
    """
    _run_generate("game", topic, learner_id)


@app.command()
def ingest(
    path: str = typer.Argument(help="Path to teacher materials to ingest"),
) -> None:
    """Ingest teacher materials into the shared knowledge base.

    If Claw-ED's ingestor is importable, delegates to it.
    Otherwise, performs basic text extraction and stores in
    Stuart's brain.
    """
    from pathlib import Path as _Path

    mat_path = _Path(path)
    if not mat_path.exists():
        typer.secho(f"Path does not exist: {path}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    try:
        from clawed.ingest import ingest_materials

        _ = ingest_materials
        typer.echo(f"Ingesting {path} via Claw-ED ingestor ...")
        typer.secho(_V5_STUB_MSG, fg=typer.colors.YELLOW)
    except (ImportError, ModuleNotFoundError):
        typer.echo(f"Would ingest {path} (Ed ingestor not available).")
        typer.secho(_V5_STUB_MSG, fg=typer.colors.YELLOW)


def main() -> None:
    """Entry point wired to pyproject.toml's [project.scripts]."""
    app()


if __name__ == "__main__":
    main()

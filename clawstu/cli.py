"""clawstu — the Claw-STU console entry point.

Thin wrapper over the HTTP API and the proactive scheduler. No
pedagogical logic lives here; every command calls functions that
already exist in clawstu.api, clawstu.orchestrator, or (Phase 4+)
clawstu.memory / clawstu.scheduler.

Commands:
  clawstu serve                              start the FastAPI app
  clawstu doctor                             self-diagnosis
  clawstu scheduler run-once --task <name>   run a proactive task once
  clawstu profile export <learner_id>        export profile + brain tarball
  clawstu profile import <path>              restore a tarball
"""
from __future__ import annotations

import typer

app: typer.Typer = typer.Typer(
    name="clawstu",
    help=(
        "Stuart — a personal learning agent that grows with the "
        "student. Made by a teacher, for learners."
    ),
    no_args_is_help=True,
    add_completion=False,
)

scheduler_app: typer.Typer = typer.Typer(help="Proactive-scheduler administration.")
profile_app: typer.Typer = typer.Typer(help="Learner profile portability.")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(profile_app, name="profile")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
) -> None:
    """Start the FastAPI app + embedded scheduler.

    Binds to 127.0.0.1 by default (localhost-only). Pass --host 0.0.0.0
    explicitly if you know what you're doing.
    """
    typer.echo(f"clawstu serve: starting uvicorn on {host}:{port}")
    typer.echo(
        "NOTE: Phase 1 serve is a placeholder. Full lifespan with the "
        "embedded scheduler lands in Phase 6."
    )


@app.command()
def doctor() -> None:
    """Self-diagnosis: config load, provider connectivity, SQLite, FTS5."""
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
    typer.echo("  provider reachability: DEFERRED (Phase 2)")
    typer.echo("  sqlite + FTS5: DEFERRED (Phase 3)")
    typer.echo("  embeddings model: DEFERRED (Phase 4)")


@scheduler_app.command("run-once")
def scheduler_run_once(
    task: str = typer.Option(..., "--task", help="Task name to run."),
) -> None:
    """Run one proactive task immediately (Phase 6)."""
    typer.echo(f"clawstu scheduler run-once --task {task}")
    typer.secho(
        "NOTE: the scheduler + task registry land in Phase 6. "
        "This command is a placeholder in Phase 1.",
        fg=typer.colors.YELLOW,
    )


@profile_app.command("export")
def profile_export(
    learner_id: str = typer.Argument(...),
    out: str = typer.Option(..., "--out", "-o", help="Output tarball path."),
) -> None:
    """Export a learner profile + brain pages as a tarball (Phase 7)."""
    typer.echo(f"clawstu profile export {learner_id} --out {out}")
    typer.secho(
        "NOTE: profile/brain tarball export lands in Phase 7. "
        "This command is a placeholder in Phase 1.",
        fg=typer.colors.YELLOW,
    )


@profile_app.command("import")
def profile_import(path: str = typer.Argument(...)) -> None:
    """Import a previously exported learner tarball (Phase 7)."""
    typer.echo(f"clawstu profile import {path}")
    typer.secho(
        "NOTE: profile import lands in Phase 7. "
        "This command is a placeholder in Phase 1.",
        fg=typer.colors.YELLOW,
    )


def main() -> None:
    """Entry point wired to pyproject.toml's [project.scripts]."""
    app()


if __name__ == "__main__":
    main()

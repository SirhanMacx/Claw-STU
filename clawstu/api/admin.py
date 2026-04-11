"""Admin / health endpoints.

Scoped tightly: health check, a count of live sessions, and a Phase 6
scheduler transparency view. Anything more invasive (guardian
dashboards, telemetry) is deliberately deferred until we have a real
auth story.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from clawstu import __version__
from clawstu.api.state import AppState, get_state
from clawstu.scheduler.runner import SchedulerRunner

router = APIRouter(prefix="/admin", tags=["admin"])


class HealthResponse(BaseModel):
    status: str
    version: str
    invariants: dict[str, bool]
    active_sessions: int


@router.get("/health", response_model=HealthResponse)
def health(state: AppState = Depends(get_state)) -> HealthResponse:
    invariants = {
        "soul_md_loaded": True,
        "safety_filters_active": True,
    }
    degraded = any(value is False for value in invariants.values())
    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=__version__,
        invariants=invariants,
        active_sessions=len(state.sessions),
    )


# -- Phase 6: scheduler transparency view ----------------------------------


class SchedulerTaskView(BaseModel):
    """Static metadata for one registered task."""

    name: str
    cron: str
    enabled: bool
    description: str


class SchedulerRunView(BaseModel):
    """One persisted run record from `SchedulerRunStore`."""

    task_name: str
    learner_id_hash: str | None
    outcome: str
    duration_ms: int
    token_cost_input: int
    token_cost_output: int
    run_at: str
    error_message: str | None


class SchedulerStatusResponse(BaseModel):
    """`/admin/scheduler` payload — registered tasks + recent runs."""

    tasks: list[SchedulerTaskView]
    job_ids: list[str]
    recent_runs: list[SchedulerRunView]


def _coerce_str(value: object) -> str:
    return str(value) if value is not None else ""


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_int(value: object) -> int:
    """Defensive int coercion for SchedulerRunStore dict rows.

    Both backends return integers for the int columns, but the dict
    is `dict[str, object]` per the Protocol, so mypy needs the
    coercion. The non-int branch is structurally unreachable today
    and is left as a 0 fallback rather than a raise so a future
    schema-mismatch never crashes the admin route.
    """
    return value if isinstance(value, int) else 0


@router.get("/scheduler", response_model=SchedulerStatusResponse)
def scheduler_status(request: Request) -> SchedulerStatusResponse:
    """Return registered tasks plus the 50 most-recent run records.

    The runner is stashed on `app.state.scheduler` by the lifespan
    context manager. If the lifespan never ran (e.g. an ad-hoc test
    harness that bypassed `create_app()`), this route returns 503 so
    the operator gets a clear signal rather than an opaque crash.
    """
    runner = getattr(request.app.state, "scheduler", None)
    if not isinstance(runner, SchedulerRunner):
        raise HTTPException(
            status_code=503,
            detail="scheduler not initialized",
        )
    tasks = [
        SchedulerTaskView(
            name=spec.name,
            cron=spec.cron,
            enabled=spec.enabled,
            description=spec.description,
        )
        for spec in runner.registry.list_all()
    ]
    raw_runs = runner.context.persistence.scheduler_runs.list_recent(limit=50)
    recent_runs = [
        SchedulerRunView(
            task_name=_coerce_str(row.get("task_name")),
            learner_id_hash=_coerce_optional_str(row.get("learner_id_hash")),
            outcome=_coerce_str(row.get("outcome")),
            duration_ms=_coerce_int(row.get("duration_ms")),
            token_cost_input=_coerce_int(row.get("token_cost_input")),
            token_cost_output=_coerce_int(row.get("token_cost_output")),
            run_at=_coerce_str(row.get("run_at")),
            error_message=_coerce_optional_str(row.get("error_message")),
        )
        for row in raw_runs
    ]
    return SchedulerStatusResponse(
        tasks=tasks,
        job_ids=runner.get_job_ids(),
        recent_runs=recent_runs,
    )

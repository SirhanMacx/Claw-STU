"""Claw-STU MCP Server -- expose Stuart's learning tools via Model Context Protocol.

This lets Claude Code, Claude Desktop, and other MCP clients call
Stuart's capabilities directly: ask Socratic questions, query the
concept wiki, check learner progress, review due concepts, and
start learning sessions.

Uses stdio transport (the MCP standard). The client process spawns
this server and communicates over stdin/stdout.

Usage:
    clawstu mcp-server
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Claw-STU",
    instructions=(
        "Claw-STU (Stuart) is a personal learning agent that grows with the "
        "student. Use clawstu_ask for one-shot Socratic questions, "
        "clawstu_wiki for per-student concept pages, clawstu_progress for "
        "learner dashboards, clawstu_review for spaced-review due concepts, "
        "and clawstu_learn_session to start an adaptive learning session."
    ),
)


def _resolve_stores() -> Any:
    """Build the default store bundle for data access.

    Lazy import so the MCP server starts fast and doesn't pull in heavy
    modules until the first tool call.
    """
    from clawstu.cli_state import default_stores

    return default_stores()


def _resolve_learner_id(
    persistence: Any, learner_id: str | None,
) -> str | None:
    """Resolve a learner ID, falling back to the most recent learner."""
    if learner_id:
        return learner_id
    try:
        from clawstu.cli_state import most_recent_learner

        return most_recent_learner(persistence)
    except Exception:
        return None


# -- Tool definitions --------------------------------------------------------


@mcp.tool()
async def clawstu_ask(
    question: str,
    learner_id: str = "",
) -> str:
    """Ask Stuart a one-shot Socratic question.

    Routes through the reasoning chain with TaskKind.SOCRATIC_DIALOGUE.
    If a learner_id is provided (or a recent learner exists), the answer
    is personalized with their learning context. No session state is
    created or modified.

    Args:
        question: The question to ask (e.g., "What is photosynthesis?")
        learner_id: Optional learner ID for personalized answers
    """
    from clawstu.api.main import build_providers
    from clawstu.memory.context import build_learner_context
    from clawstu.orchestrator.chain import ReasoningChain
    from clawstu.orchestrator.config import load_config
    from clawstu.orchestrator.router import ModelRouter
    from clawstu.orchestrator.task_kinds import TaskKind

    bundle = _resolve_stores()
    resolved_id = _resolve_learner_id(
        bundle.persistence, learner_id or None,
    )

    cfg = load_config()
    providers = build_providers(cfg)
    router = ModelRouter(config=cfg, providers=providers)
    chain = ReasoningChain(router=router)

    effective_question = question
    if resolved_id:
        profile = bundle.persistence.learners.get(resolved_id)
        if profile is not None:
            context = build_learner_context(
                learner_id=resolved_id,
                concept=question[:50],
                brain_store=bundle.brain_store,
                kg_store=bundle.persistence.kg,
                max_chars=2000,
            )
            if context.text.strip():
                effective_question = (
                    f"<learner_context>\n{context.text}\n"
                    f"</learner_context>\n\n{question}"
                )

    try:
        answer = await chain.ask(
            effective_question,
            task_kind=TaskKind.SOCRATIC_DIALOGUE,
        )
    finally:
        for provider in providers.values():
            client = getattr(provider, "_client", None)
            if client is not None and hasattr(client, "aclose"):
                await client.aclose()

    return json.dumps({
        "answer": answer,
        "learner_id": resolved_id or "anonymous",
    })


@mcp.tool()
async def clawstu_wiki(
    concept: str,
    learner_id: str = "",
) -> str:
    """Look up a concept in the per-student wiki.

    Returns a markdown-formatted concept page compiled from the
    learner's session history, including truth statements,
    misconceptions, and tied primary sources.

    Args:
        concept: Concept name (e.g., "french_revolution_causes")
        learner_id: Optional learner ID (defaults to most recent)
    """
    from clawstu.memory.wiki import generate_concept_wiki

    bundle = _resolve_stores()
    resolved_id = _resolve_learner_id(
        bundle.persistence, learner_id or None,
    )

    if not resolved_id:
        return json.dumps({
            "error": "no learner found",
            "message": "Run `clawstu learn` to start your first session.",
        })

    wiki_md = generate_concept_wiki(
        learner_id=resolved_id,
        concept=concept,
        brain_store=bundle.brain_store,
        kg_store=bundle.persistence.kg,
    )

    return json.dumps({
        "wiki_markdown": wiki_md,
        "concept": concept,
        "learner_id": resolved_id,
    })


@mcp.tool()
async def clawstu_progress(
    learner_id: str = "",
) -> str:
    """Show learner dashboard: ZPD per domain, modality mix, session count.

    Returns a JSON summary of the learner's current state including
    zone of proximal development estimates, modality outcomes, and
    session history metadata.

    Args:
        learner_id: Optional learner ID (defaults to most recent)
    """
    bundle = _resolve_stores()
    resolved_id = _resolve_learner_id(
        bundle.persistence, learner_id or None,
    )

    if not resolved_id:
        return json.dumps({
            "error": "no learner found",
            "message": "Run `clawstu learn` to start your first session.",
        })

    profile = bundle.persistence.learners.get(resolved_id)
    if profile is None:
        return json.dumps({"error": f"learner {resolved_id!r} not found"})

    zpd_data: dict[str, Any] = {}
    for domain, zpd in profile.zpd_by_domain.items():
        zpd_data[domain.value] = {
            "level": zpd.level,
            "confidence": zpd.confidence,
        }

    modality_data: dict[str, dict[str, int]] = {}
    for mo in profile.modality_outcomes:
        key = mo.modality.value
        if key not in modality_data:
            modality_data[key] = {"correct": 0, "total": 0}
        modality_data[key]["total"] += 1
        if mo.correct:
            modality_data[key]["correct"] += 1

    sessions = bundle.persistence.sessions.list(resolved_id)

    return json.dumps({
        "learner_id": resolved_id,
        "zpd": zpd_data,
        "modality": modality_data,
        "sessions": len(sessions),
    })


@mcp.tool()
async def clawstu_review(
    learner_id: str = "",
) -> str:
    """Show concepts due for spaced review.

    A concept is due when its most recent check-for-understanding or
    calibration event is older than 7 days.

    Args:
        learner_id: Optional learner ID (defaults to most recent)
    """
    from datetime import UTC, datetime, timedelta

    from clawstu.profile.model import EventKind

    bundle = _resolve_stores()
    resolved_id = _resolve_learner_id(
        bundle.persistence, learner_id or None,
    )

    if not resolved_id:
        return json.dumps({
            "error": "no learner found",
            "message": "Run `clawstu learn` to start your first session.",
        })

    profile = bundle.persistence.learners.get(resolved_id)
    if profile is None:
        return json.dumps({"error": f"learner {resolved_id!r} not found"})

    cutoff = datetime.now(tz=UTC) - timedelta(days=7)
    review_kinds = {
        EventKind.CHECK_FOR_UNDERSTANDING,
        EventKind.CALIBRATION_ANSWER,
    }

    concept_last_seen: dict[str, datetime] = {}
    for event in profile.events:
        if event.kind in review_kinds and event.concept:
            prev = concept_last_seen.get(event.concept)
            if prev is None or event.timestamp > prev:
                concept_last_seen[event.concept] = event.timestamp

    due_concepts = [
        {"concept": concept, "last_seen": ts.isoformat()}
        for concept, ts in sorted(concept_last_seen.items())
        if ts < cutoff
    ]

    return json.dumps({
        "learner_id": resolved_id,
        "due_concepts": due_concepts,
        "total_concepts": len(concept_last_seen),
    })


@mcp.tool()
async def clawstu_learn_session(
    topic: str,
    learner_id: str = "Ada",
    age_bracket: str = "middle",
) -> str:
    """Start a learning session and return the session metadata.

    Creates a new session for the given topic and learner. The session
    is persisted so it can be continued via the CLI or API. Use
    clawstu_ask for one-shot questions instead of full sessions.

    Args:
        topic: Topic to learn about (e.g., "photosynthesis")
        learner_id: Learner name or ID (default: "Ada")
        age_bracket: Age bracket: early_elementary, late_elementary,
            middle, early_high, late_high, adult (default: "middle")
    """
    from clawstu.engagement.session import Session
    from clawstu.profile.model import AgeBracket, Domain, LearnerProfile

    bundle = _resolve_stores()

    # Resolve age bracket.
    try:
        bracket = AgeBracket(age_bracket)
    except ValueError:
        bracket = AgeBracket.MIDDLE

    # Ensure the learner exists.
    existing_profile = bundle.persistence.learners.get(learner_id)
    if existing_profile is None:
        new_profile = LearnerProfile(
            learner_id=learner_id,
            age_bracket=bracket,
        )
        bundle.persistence.learners.upsert(new_profile)

    session = Session(
        learner_id=learner_id,
        topic=topic,
        domain=Domain.OTHER,
    )

    return json.dumps({
        "session_id": session.id,
        "learner_id": learner_id,
        "topic": topic,
        "domain": session.domain.value,
        "phase": session.phase.value,
        "message": (
            f"Session created for {learner_id} on '{topic}'. "
            "Use `clawstu learn` CLI or the API to run the full "
            "teach-assess-adapt loop."
        ),
    })


def _get_tool_registry() -> list[str]:
    """Return the list of registered tool names. Used by tests."""
    return [
        "clawstu_ask",
        "clawstu_wiki",
        "clawstu_progress",
        "clawstu_review",
        "clawstu_learn_session",
    ]


def run_mcp_server() -> None:
    """Run the MCP server using stdio transport (the standard MCP transport)."""
    mcp.run(transport="stdio")

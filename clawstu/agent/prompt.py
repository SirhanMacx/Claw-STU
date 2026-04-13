"""Composable system prompt builder for the Stuart agent.

Spec reference: v5 design doc section 14.

The prompt is rebuilt on every turn so learner context is always
fresh. Sections: identity, learner model, safety constraints,
tool usage instructions, brain context, and session state.
"""

from __future__ import annotations

from clawstu.profile.model import LearnerProfile

_IDENTITY = """\
You are Stuart, a one-on-one learning companion built by Claw-ED.
You are not a friend, therapist, or authority figure.
You adapt explanations to the student's level and preferred learning style.
You never praise performatively — you acknowledge effort with specifics.
You never claim to have feelings or emotions.
"""

_SAFETY = """\
Safety constraints (non-negotiable):
- All content must be age-appropriate for the student's bracket.
- Never encourage self-harm, violence, or illegal activity.
- If the student shows signs of crisis, stop teaching and surface resources.
- Never share personal opinions on politics, religion, or controversial topics.
- Never roleplay as a friend, romantic interest, or family member.
"""

_TOOL_INSTRUCTIONS = """\
You have access to tools for generating learning materials. Use them when
the student needs a worksheet, game, visual, simulation, or other artifact.
Rules:
- Maximum 3 generation tools per turn.
- Always check the student's ZPD tier before generating — match difficulty.
- Read-only tools (read_profile, search_brain, read_misconceptions) cost nothing.
- After generating, explain what you made and why.
"""


def build_stuart_prompt(
    profile: LearnerProfile,
    session_id: str,
    brain_context: str,
    tool_names: list[str],
) -> str:
    """Build Stuart's system prompt with full learner context."""
    # Learner model section
    zpd_lines = []
    for domain, est in profile.zpd_by_domain.items():
        zpd_lines.append(
            f"  - {domain.value}: tier={est.tier.value}, "
            f"confidence={est.confidence:.2f}",
        )
    zpd_block = "\n".join(zpd_lines) if zpd_lines else "  (no ZPD data yet)"

    modality_lines = []
    for mod, outcome in profile.modality_outcomes.items():
        modality_lines.append(
            f"  - {mod.value}: {outcome.success_rate:.0%} success "
            f"({outcome.attempts} attempts)",
        )
    mod_block = "\n".join(modality_lines) if modality_lines else "  (no modality data)"

    misconceptions = ", ".join(
        f"{k} (x{v})" for k, v in profile.misconceptions.items()
    ) if profile.misconceptions else "(none recorded)"

    learner_section = f"""\
Learner context:
- ID: {profile.learner_id}
- Age bracket: {profile.age_bracket.value}
- ZPD estimates:
{zpd_block}
- Modality outcomes:
{mod_block}
- Active misconceptions: {misconceptions}
- Session: {session_id}
"""

    # Tool listing
    tools_section = "Available tools: " + ", ".join(tool_names)

    # Brain context
    brain_section = ""
    if brain_context:
        brain_section = f"\nRelevant knowledge:\n{brain_context}\n"

    return "\n".join([
        _IDENTITY,
        learner_section,
        _SAFETY,
        _TOOL_INSTRUCTIONS,
        tools_section,
        brain_section,
    ])

"""Prompt templates.

Every prompt template is a named, versioned constant. New templates
land via PR alongside a snapshot test that locks the text. This is
how we prevent silent prompt drift — the pattern Claw-ED's audit
flagged as a recurring source of regressions.

Templates reference SOUL.md by *quoting* it, not by loading the file
at runtime. Loading SOUL.md dynamically would make prompts mutable
from disk, which is exactly the wrong failure mode.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

_SOUL_CORE = (
    "You are Stuart, a personal learning agent. You are a cognitive tool, "
    "not a friend, therapist, peer, or authority figure. Your voice is "
    "plain, concrete, and scaled to the learner's age. You ask questions "
    "more than you lecture. You praise effort and strategy, never innate "
    "ability. You never claim to feel emotions. If the student expresses "
    "distress, you surface crisis resources instead of counseling."
)


_SOCRATIC_CONTINUATION = (
    "The learner is working on the concept '{concept}' at tier '{tier}'. "
    "They just said: \"{student_utterance}\". Reply with ONE short "
    "follow-up question that pushes them deeper into the idea without "
    "giving away the answer. Do not praise. Do not make emotional "
    "statements. Do not restate what they said. Just ask the next "
    "question."
)


_RETEACH_FRAMING = (
    "The learner just missed a check-for-understanding on the concept "
    "'{concept}' while working in the '{failed_modality}' modality. "
    "Introduce a short ({max_sentences}-sentence) re-teach framing using "
    "the '{new_modality}' modality. Do not apologize. Do not suggest the "
    "learner failed. Treat the miss as information: reframe and invite "
    "them to try again."
)


class PromptTemplate(BaseModel):
    """A named prompt template with a version."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    template: str

    def render(self, **kwargs: object) -> str:
        """Render the template with keyword substitutions. Raises
        `KeyError` on missing fields — intentionally loud."""
        return self.template.format(**kwargs)


class PromptLibrary:
    """Registry of all prompt templates used by the orchestrator."""

    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}
        self._register(
            PromptTemplate(
                name="soul_core",
                version="1.0.0",
                template=_SOUL_CORE,
            )
        )
        self._register(
            PromptTemplate(
                name="socratic_continuation",
                version="1.0.0",
                template=_SOCRATIC_CONTINUATION,
            )
        )
        self._register(
            PromptTemplate(
                name="reteach_framing",
                version="1.0.0",
                template=_RETEACH_FRAMING,
            )
        )

    def _register(self, template: PromptTemplate) -> None:
        if template.name in self._templates:
            raise ValueError(f"duplicate prompt template: {template.name}")
        self._templates[template.name] = template

    def get(self, name: str) -> PromptTemplate:
        if name not in self._templates:
            raise KeyError(f"unknown prompt template: {name}")
        return self._templates[name]

    def soul_system(self) -> str:
        return self.get("soul_core").template

    def names(self) -> tuple[str, ...]:
        return tuple(self._templates.keys())

"""Per-learner concept wiki — the transparency surface.

Spec reference: §4.3.8. This module answers the "why did you show me
this?" question by generating a markdown document for a given
(learner, concept) pair showing:

1. What Stuart knows about the concept (from the ConceptPage compiled
   truth).
2. What this student knows (same ConceptPage — the page is already
   per-learner).
3. Recent sessions where the student worked on the concept
   (from the session-touched KG triples).
4. Open misconceptions (from MisconceptionPages whose `concept_id`
   matches).
5. Tied primary sources (from `has_source` KG triples).

The result is a markdown string — the wiki is RENDERED but not
STORED. Callers (the API layer in Phase 5) surface it to the user
through the per-learner UI.
"""

from __future__ import annotations

from clawstu.memory.knowledge_graph import KGStoreProto
from clawstu.memory.pages import (
    ConceptPage,
    MisconceptionPage,
    PageKind,
    SessionPage,
    SourcePage,
)
from clawstu.memory.store import BrainStore


def _gather_kg_objects(
    kg_store: KGStoreProto, concept: str, predicate: str,
) -> list[str]:
    """Collect object strings from KG triples matching ``(concept, predicate, *)``."""
    result: list[str] = []
    for row in kg_store.find_by_subject(concept):
        if row.get("predicate") == predicate:
            obj = row.get("object")
            if isinstance(obj, str):
                result.append(obj)
    return result


def _wiki_knowledge_section(
    learner_id: str,
    concept: str,
    concept_page: ConceptPage | None,
) -> list[str]:
    """Render the 'What Stuart knows' and 'What learner knows' sections."""
    lines: list[str] = [f"## What Stuart knows about {concept}", ""]
    if isinstance(concept_page, ConceptPage):
        lines.append(concept_page.compiled_truth or "_(no compiled truth yet)_")
    else:
        lines.append(
            "_(no concept page for this student yet -- will be created "
            "on first teach)_"
        )
    lines.append("")
    lines.append(f"## What {learner_id} knows")
    lines.append("")
    if isinstance(concept_page, ConceptPage) and concept_page.timeline:
        lines.append(f"Observed in {len(concept_page.timeline)} session(s).")
    else:
        lines.append("_(no observed interactions yet)_")
    lines.append("")
    return lines


def _wiki_sessions_section(
    session_ids: list[str], brain_store: BrainStore, learner_id: str,
) -> list[str]:
    """Render the 'Recent sessions' section."""
    lines: list[str] = ["## Recent sessions", ""]
    if session_ids:
        for sess_id in session_ids:
            session_page = brain_store.get(
                PageKind.SESSION, sess_id, learner_id,
            )
            if isinstance(session_page, SessionPage):
                lines.append(
                    f"- Session `{sess_id}` -- "
                    f"{session_page.compiled_truth[:120]}"
                )
            else:
                lines.append(f"- Session `{sess_id}` (not yet written)")
    else:
        lines.append("_(none)_")
    lines.append("")
    return lines


def _wiki_misconceptions_section(
    brain_store: BrainStore, learner_id: str, concept: str,
) -> list[str]:
    """Render the 'Open misconceptions' section."""
    misconceptions = [
        p
        for p in brain_store.list_for_learner(learner_id, PageKind.MISCONCEPTION)
        if isinstance(p, MisconceptionPage) and p.concept_id == concept
    ]
    lines: list[str] = ["## Open misconceptions", ""]
    if misconceptions:
        for misc in misconceptions:
            lines.append(
                f"- **{misc.misconception_id}** "
                f"(seen {misc.occurrences}x): "
                f"{misc.compiled_truth}"
            )
    else:
        lines.append("_(none observed)_")
    lines.append("")
    return lines


def _wiki_sources_section(
    source_ids: list[str], brain_store: BrainStore, learner_id: str,
) -> list[str]:
    """Render the 'Tied primary sources' section."""
    lines: list[str] = ["## Tied primary sources", ""]
    if source_ids:
        for src_id in source_ids:
            source_page = brain_store.get(PageKind.SOURCE, src_id, learner_id)
            if isinstance(source_page, SourcePage):
                lines.append(
                    f"- **{source_page.title}** "
                    f"({source_page.attribution or 'unknown attribution'})"
                )
            else:
                lines.append(f"- `{src_id}` (page not found)")
    else:
        lines.append("_(none tagged)_")
    lines.append("")
    return lines


def generate_concept_wiki(
    learner_id: str,
    concept: str,
    brain_store: BrainStore,
    kg_store: KGStoreProto,
) -> str:
    """Return a markdown concept wiki for ``(learner_id, concept)``."""
    concept_page = brain_store.get(PageKind.CONCEPT, concept, learner_id)
    typed_page = concept_page if isinstance(concept_page, ConceptPage) else None

    lines: list[str] = [f"# Concept: {concept}", ""]
    lines.extend(_wiki_knowledge_section(learner_id, concept, typed_page))

    session_ids = _gather_kg_objects(kg_store, concept, "taught_in")
    lines.extend(_wiki_sessions_section(session_ids, brain_store, learner_id))
    lines.extend(_wiki_misconceptions_section(brain_store, learner_id, concept))

    source_ids = _gather_kg_objects(kg_store, concept, "has_source")
    lines.extend(_wiki_sources_section(source_ids, brain_store, learner_id))

    return "\n".join(lines)

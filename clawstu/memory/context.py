"""Context assembly — pull a bounded brain slice for an LLM prompt.

Spec reference: §4.3.5.

``build_learner_context`` composes a `LearnerContext` by walking the
brain in priority order:

1. LearnerPage compiled truth — always.
2. ConceptPage compiled truth for the target concept — always.
3. Related concepts (via KG `find_related`, depth=1), each
   ConceptPage's compiled truth.
4. The last N SessionPages for this learner (N=3 by default).
5. MisconceptionPages whose ``concept_id`` matches the target.
6. SourcePages associated with the target concept via KG triples
   (``(concept, has_source, source_id)``).

The assembled text is truncated at ``max_chars``; ``source_pages``
records the page keys that actually contributed content (in inclusion
order), letting the caller answer "which pages did you use?" without
reparsing the text.

Priority order matters because a tight ``max_chars`` budget prunes
lower-priority sources first. The LearnerPage always makes it in
unless its compiled truth alone blows the budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clawstu.memory.knowledge_graph import KGStoreProto, find_related
from clawstu.memory.pages import (
    BrainPage,
    ConceptPage,
    LearnerPage,
    MisconceptionPage,
    PageKind,
    SessionPage,
    SourcePage,
)
from clawstu.memory.store import BrainStore


@dataclass(frozen=True)
class LearnerContext:
    """A bounded prompt-injectable brain slice."""

    text: str
    source_pages: tuple[str, ...] = field(default_factory=tuple)


def _header(title: str) -> str:
    return f"## {title}\n"


def _page_key(page: BrainPage) -> str:
    """Return a stable `<kind>:<id>` key for a page.

    Duplicated from search.py rather than importing it here — context.py
    is a sibling layer that doesn't want to pull the search module's
    numpy dependency just for a key helper.
    """
    kind = page.kind.value
    if isinstance(page, LearnerPage):
        return f"{kind}:{page.learner_id}"
    if isinstance(page, ConceptPage):
        return f"{kind}:{page.concept_id}"
    if isinstance(page, SessionPage):
        return f"{kind}:{page.session_id}"
    if isinstance(page, SourcePage):
        return f"{kind}:{page.source_id}"
    if isinstance(page, MisconceptionPage):
        return f"{kind}:{page.misconception_id}"
    return f"{kind}:unknown"


class _ContextAssembler:
    """Accumulates bounded context chunks with a char budget."""

    def __init__(self, max_chars: int) -> None:
        self.chunks: list[str] = []
        self.contributing_keys: list[str] = []
        self.remaining = max_chars

    def try_append(self, key: str, title: str, body: str) -> bool:
        """Attempt to add a section; return True if it fit.

        Partial fit truncates ``body`` with a trailing ``...`` marker so
        the consumer can see the section was clipped.
        """
        header = _header(title)
        trailer = "\n\n"
        needed = len(header) + len(body) + len(trailer)
        if self.remaining <= 0:
            return False
        if needed <= self.remaining:
            self.chunks.append(header + body + trailer)
            self.contributing_keys.append(key)
            self.remaining -= needed
            return True
        reserve = len(header) + len(trailer) + 3
        if self.remaining <= reserve:
            return False
        room = self.remaining - reserve
        truncated = body[:room].rstrip()
        self.chunks.append(header + truncated + "..." + trailer)
        self.contributing_keys.append(key)
        self.remaining -= len(header) + len(truncated) + 3 + len(trailer)
        return True

    def build(self) -> LearnerContext:
        """Return the assembled LearnerContext."""
        text = "".join(self.chunks).rstrip("\n") + (
            "\n" if self.chunks else ""
        )
        return LearnerContext(
            text=text, source_pages=tuple(self.contributing_keys),
        )


def _append_learner_page(
    asm: _ContextAssembler,
    brain_store: BrainStore,
    learner_id: str,
) -> None:
    """Append the LearnerPage compiled truth to the assembler."""
    learner_page = brain_store.get(PageKind.LEARNER, learner_id, learner_id)
    if isinstance(learner_page, LearnerPage):
        asm.try_append(
            _page_key(learner_page), "Learner", learner_page.compiled_truth,
        )


def _append_concept_page(
    asm: _ContextAssembler,
    brain_store: BrainStore,
    concept: str,
    learner_id: str,
) -> None:
    """Append the target ConceptPage compiled truth to the assembler."""
    concept_page = brain_store.get(PageKind.CONCEPT, concept, learner_id)
    if isinstance(concept_page, ConceptPage):
        asm.try_append(
            _page_key(concept_page),
            f"Concept: {concept}",
            concept_page.compiled_truth,
        )


def _append_related_concepts(
    asm: _ContextAssembler,
    brain_store: BrainStore,
    kg_store: KGStoreProto,
    concept: str,
    learner_id: str,
) -> None:
    """Append related concept pages via KG (depth 1) to the assembler."""
    related = find_related(kg_store, concept, depth=1)
    for related_concept in sorted(related):
        related_page = brain_store.get(
            PageKind.CONCEPT, related_concept, learner_id,
        )
        if not isinstance(related_page, ConceptPage):
            continue
        if not asm.try_append(
            _page_key(related_page),
            f"Related concept: {related_concept}",
            related_page.compiled_truth,
        ):
            break


def _append_session_history(
    asm: _ContextAssembler,
    brain_store: BrainStore,
    learner_id: str,
    session_history_size: int,
) -> None:
    """Append the last N SessionPages to the assembler."""
    session_pages = [
        p
        for p in brain_store.list_for_learner(learner_id, PageKind.SESSION)
        if isinstance(p, SessionPage)
    ]
    session_pages.sort(key=lambda p: p.updated_at, reverse=True)
    for session_page in session_pages[:session_history_size]:
        if not asm.try_append(
            _page_key(session_page),
            f"Recent session: {session_page.session_id}",
            session_page.compiled_truth,
        ):
            break


def _append_misconceptions(
    asm: _ContextAssembler,
    brain_store: BrainStore,
    concept: str,
    learner_id: str,
) -> None:
    """Append MisconceptionPages tied to the target concept."""
    misconception_pages = [
        p
        for p in brain_store.list_for_learner(
            learner_id, PageKind.MISCONCEPTION,
        )
        if isinstance(p, MisconceptionPage) and p.concept_id == concept
    ]
    for misconception_page in misconception_pages:
        if not asm.try_append(
            _page_key(misconception_page),
            f"Misconception: {misconception_page.misconception_id}",
            misconception_page.compiled_truth,
        ):
            break


def _append_source_pages(
    asm: _ContextAssembler,
    brain_store: BrainStore,
    kg_store: KGStoreProto,
    concept: str,
    learner_id: str,
) -> None:
    """Append SourcePages linked to the target concept via KG triples."""
    source_ids: list[str] = []
    for row in kg_store.find_by_subject(concept):
        if row.get("predicate") == "has_source":
            obj = row.get("object")
            if isinstance(obj, str):
                source_ids.append(obj)
    seen_sources: set[str] = set()
    for source_id in source_ids:
        if source_id in seen_sources:
            continue
        seen_sources.add(source_id)
        source_page = brain_store.get(PageKind.SOURCE, source_id, learner_id)
        if not isinstance(source_page, SourcePage):
            continue
        if not asm.try_append(
            _page_key(source_page),
            f"Source: {source_page.title}",
            source_page.compiled_truth,
        ):
            break


def build_learner_context(
    *,
    learner_id: str,
    concept: str,
    brain_store: BrainStore,
    kg_store: KGStoreProto,
    max_chars: int = 3000,
    session_history_size: int = 3,
) -> LearnerContext:
    """Return a bounded `LearnerContext` for ``(learner_id, concept)``."""
    if max_chars <= 0:
        return LearnerContext(text="", source_pages=())

    asm = _ContextAssembler(max_chars)
    _append_learner_page(asm, brain_store, learner_id)
    _append_concept_page(asm, brain_store, concept, learner_id)
    _append_related_concepts(asm, brain_store, kg_store, concept, learner_id)
    _append_session_history(asm, brain_store, learner_id, session_history_size)
    _append_misconceptions(asm, brain_store, concept, learner_id)
    _append_source_pages(asm, brain_store, kg_store, concept, learner_id)
    return asm.build()

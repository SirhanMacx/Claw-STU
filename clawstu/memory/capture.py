"""Source capture — save student-shared materials as SourcePages.

Spec reference: §4.3.1 (files) and §4.3.2 (source pages). Phase 4
ships the page-minting half of capture_source; the API wiring (an
HTTP endpoint that accepts an upload, checks content-safety, and
calls this function) lands in Phase 5.

The capture helper is intentionally small: the content filter and
age-bracket gating live in the API layer, not here. Memory writes
what it's told to write.
"""

from __future__ import annotations

from datetime import UTC, datetime

from clawstu.memory.pages import SourcePage
from clawstu.memory.store import BrainStore


def capture_source(
    text: str,
    *,
    source_id: str,
    title: str,
    age_bracket: str,
    brain_store: BrainStore,
    attribution: str = "",
    learner_id: str = "",
) -> SourcePage:
    """Save a student-shared source as a SourcePage and return it.

    SourcePages are global (not per-learner), so ``learner_id`` is
    only used to satisfy the BrainStore API signature — it's ignored
    for the source file path. Callers may pass an empty string.

    Parameters
    ----------
    text
        The source body text. Stored in ``compiled_truth``. Phase 5
        will add content-safety and HAPP-extraction passes upstream
        before this function is called.
    source_id
        Stable slug for the source. Also the filename (after
        sanitization by the BrainStore).
    title
        Display title, e.g., "Emancipation Proclamation".
    age_bracket
        Plain string (memory does not import profile.AgeBracket).
    """
    page = SourcePage(
        source_id=source_id,
        title=title,
        attribution=attribution,
        age_bracket=age_bracket,
        updated_at=datetime.now(UTC),
        compiled_truth=text,
    )
    brain_store.put(page, learner_id=learner_id or "global")
    return page

"""Primary source library.

SOUL.md §4: "Primary sources over summaries." In humanities, Stuart
should surface primary sources and teach analysis, not hand down
pre-digested conclusions. This module holds the (small, human-curated)
source library and looks sources up by ID.

Sources are **always cited**. If a block references a source ID and the
source is not in the library, that is a programmer error and we raise —
never ship uncited text to the student.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PrimarySource(BaseModel):
    """A curated primary-source excerpt with attribution."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    author: str | None
    year: int | None
    text: str
    citation: str


_DECLARATION_PREAMBLE = PrimarySource(
    id="declaration_preamble",
    title="Declaration of Independence — Preamble",
    author="Thomas Jefferson (drafter) and the Continental Congress",
    year=1776,
    text=(
        "When in the Course of human events, it becomes necessary for one "
        "people to dissolve the political bands which have connected them "
        "with another, and to assume among the powers of the earth, the "
        "separate and equal station to which the Laws of Nature and of "
        "Nature's God entitle them, a decent respect to the opinions of "
        "mankind requires that they should declare the causes which impel "
        "them to the separation."
    ),
    citation=(
        "The Declaration of Independence (1776). National Archives, "
        "Transcription of the original."
    ),
)


_SEED_SOURCES: tuple[PrimarySource, ...] = (_DECLARATION_PREAMBLE,)


class PrimarySourceLibrary:
    """Read-only lookup over the curated primary-source library."""

    def __init__(self, sources: tuple[PrimarySource, ...] | None = None) -> None:
        self._by_id: dict[str, PrimarySource] = {
            s.id: s for s in (sources if sources is not None else _SEED_SOURCES)
        }

    def get(self, source_id: str) -> PrimarySource:
        if source_id not in self._by_id:
            raise KeyError(f"unknown primary source: {source_id}")
        return self._by_id[source_id]

    def contains(self, source_id: str) -> bool:
        return source_id in self._by_id

    def ids(self) -> tuple[str, ...]:
        return tuple(self._by_id.keys())

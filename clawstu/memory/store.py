"""BrainStore — atomic file-backed CRUD for brain pages.

Spec reference: §4.3 (files layout) and §4.6.2 (hashing boundary).

On-disk layout
--------------
The store lives under a base directory (production default:
``~/.claw-stu/brain/``). Learner-scoped pages are filed under a
per-learner subdirectory keyed by a 12-char sha256 slice of the
``learner_id`` (the "hashing boundary" from spec §4.6.2; plaintext
ids stay out of disk paths). Source pages are global and live under
a flat ``sources/`` subdirectory because the same primary source
belongs to many learners.

Concrete layout::

    <base>/
        <hash12>/
            learner/<learner_id_slug>.md
            concept/<concept_id_slug>.md
            session/<session_id_slug>.md
            misconception/<misconception_id_slug>.md
            topic/<topic_id_slug>.md
        sources/
            <source_id_slug>.md

The per-page id is sanitized into a filesystem-safe slug (see
``_slug``) but plaintext, not hashed — only the learner-id
subdirectory is hashed.

Atomic writes
-------------
Every write goes through ``<target>.tmp`` + ``os.replace`` so a
crash mid-write can never leave a half-written page on disk. The
``os.replace`` call is atomic on POSIX filesystems and on NTFS via
the same syscall, which is the guarantee the spec depends on.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from clawstu.memory.pages import (
    BrainPage,
    ConceptPage,
    LearnerPage,
    MisconceptionPage,
    PageKind,
    SessionPage,
    SourcePage,
    TopicPage,
)

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]")
_HASH_LEN = 12


def _slug(raw: str) -> str:
    """Collapse a brain-page id into a filesystem-safe slug.

    Replaces any character outside ``[A-Za-z0-9._-]`` with ``_``.
    Empty strings round-trip as ``_``. Leading dots are escaped so a
    malicious id cannot produce a ``.``, ``..``, or hidden file.
    """
    if not raw:
        return "_"
    slug = _SLUG_RE.sub("_", raw)
    if slug.startswith("."):
        slug = "_" + slug.lstrip(".")
    return slug


def _learner_hash(learner_id: str) -> str:
    """Return the 12-char sha256 slice for a learner id (spec §4.6.2)."""
    digest = hashlib.sha256(learner_id.encode("utf-8")).hexdigest()
    return digest[:_HASH_LEN]


def _page_id(page: BrainPage) -> str:
    """Extract the id field from a page based on its kind."""
    if isinstance(page, LearnerPage):
        return page.learner_id
    if isinstance(page, ConceptPage):
        return page.concept_id
    if isinstance(page, SessionPage):
        return page.session_id
    if isinstance(page, SourcePage):
        return page.source_id
    if isinstance(page, MisconceptionPage):
        return page.misconception_id
    if isinstance(page, TopicPage):
        return page.topic_id
    raise TypeError(f"unsupported page type: {type(page).__name__}")


def _parse_for_kind(kind: PageKind, text: str) -> BrainPage:
    """Parse the raw markdown for a given page kind."""
    if kind is PageKind.LEARNER:
        return LearnerPage.parse(text)
    if kind is PageKind.CONCEPT:
        return ConceptPage.parse(text)
    if kind is PageKind.SESSION:
        return SessionPage.parse(text)
    if kind is PageKind.SOURCE:
        return SourcePage.parse(text)
    if kind is PageKind.MISCONCEPTION:
        return MisconceptionPage.parse(text)
    if kind is PageKind.TOPIC:
        return TopicPage.parse(text)
    raise ValueError(f"unknown page kind: {kind}")


class BrainStore:
    """Atomic file-backed CRUD for brain pages.

    Parameters
    ----------
    base_dir
        The root directory containing per-learner subdirectories and
        the shared ``sources/`` subdirectory. Created on demand.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    @property
    def base_dir(self) -> Path:
        """Return the root directory of the brain store."""
        return self._base

    # -- paths ---------------------------------------------------------

    def _target_path(
        self,
        *,
        kind: PageKind,
        page_id: str,
        learner_id: str,
    ) -> Path:
        """Compute the on-disk path for a (kind, id, learner_id) triple.

        SourcePages are global: they ignore ``learner_id`` and live under
        ``<base>/sources/<slug>.md``. All other kinds live under
        ``<base>/<hash12>/<kind>/<slug>.md``.
        """
        slug = _slug(page_id)
        if kind is PageKind.SOURCE:
            return self._base / "sources" / f"{slug}.md"
        hashed = _learner_hash(learner_id)
        kind_name: str = kind.value
        result: Path = self._base / hashed / kind_name / f"{slug}.md"
        return result

    # -- CRUD ----------------------------------------------------------

    def put(self, page: BrainPage, learner_id: str) -> None:
        """Render + atomically write a page.

        ``learner_id`` is ignored for SourcePages (global). For every
        other kind, it determines the hashed subdirectory.
        """
        target = self._target_path(
            kind=page.kind,
            page_id=_page_id(page),
            learner_id=learner_id,
        )
        self._atomic_write(target, page.render())

    def get(
        self,
        kind: PageKind,
        id: str,
        learner_id: str,
    ) -> BrainPage | None:
        """Read and parse a page by (kind, id, learner_id).

        Returns ``None`` if the file does not exist. Any I/O or parse
        error other than ``FileNotFoundError`` bubbles up — a corrupt
        page should fail loud rather than silently vanish.
        """
        target = self._target_path(kind=kind, page_id=id, learner_id=learner_id)
        if not target.exists():
            return None
        text = target.read_text(encoding="utf-8")
        return _parse_for_kind(kind, text)

    def list_for_learner(
        self,
        learner_id: str,
        kind: PageKind | None = None,
    ) -> list[BrainPage]:
        """Return every page tied to a learner.

        If ``kind`` is None, walks every subdirectory under the
        learner's hashed folder. SourcePages are excluded from this
        walk — they are global, not learner-scoped. Deterministic
        ordering (sorted by filename) so callers get repeatable
        results across runs.
        """
        pages: list[BrainPage] = []
        learner_root = self._base / _learner_hash(learner_id)
        if not learner_root.exists():
            return pages
        kinds = [kind] if kind is not None else [
            k for k in PageKind if k is not PageKind.SOURCE
        ]
        for page_kind in kinds:
            subdir = learner_root / page_kind.value
            if not subdir.exists():
                continue
            for entry in sorted(subdir.iterdir()):
                if entry.suffix != ".md":
                    continue
                text = entry.read_text(encoding="utf-8")
                pages.append(_parse_for_kind(page_kind, text))
        return pages

    def list_sources(self) -> list[SourcePage]:
        """Return every global SourcePage in deterministic order."""
        sources: list[SourcePage] = []
        subdir = self._base / "sources"
        if not subdir.exists():
            return sources
        for entry in sorted(subdir.iterdir()):
            if entry.suffix != ".md":
                continue
            sources.append(SourcePage.parse(entry.read_text(encoding="utf-8")))
        return sources

    def delete(
        self,
        kind: PageKind,
        id: str,
        learner_id: str,
    ) -> bool:
        """Delete a page. Returns True if it existed, False otherwise."""
        target = self._target_path(kind=kind, page_id=id, learner_id=learner_id)
        if not target.exists():
            return False
        target.unlink()
        return True

    # -- atomic write helper -------------------------------------------

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)

"""Modality rotation logic.

Thin wrapper around `ZPDCalibrator.recommend_modality` that enforces the
project's foundational rule:

    On a failed check, the re-teach MUST use a different modality than
    the one that failed.

Keeping this as a tiny, single-purpose class makes the invariant visible
and easy to test in isolation. The session runner delegates to this
rotator instead of calling into ZPD directly, so if we ever want to
change how rotation works we change it in exactly one place.
"""

from __future__ import annotations

from src.profile.model import LearnerProfile, Modality
from src.profile.zpd import ZPDCalibrator


class ModalityRotator:
    """Selects the next modality, guaranteeing a change on re-teach."""

    def __init__(self, calibrator: ZPDCalibrator | None = None) -> None:
        self._calibrator = calibrator or ZPDCalibrator()

    def initial(self, profile: LearnerProfile) -> Modality:
        """Pick the first modality of a session."""
        return self._calibrator.recommend_modality(profile)

    def rotate_after_failure(
        self,
        profile: LearnerProfile,
        failed_modality: Modality,
    ) -> Modality:
        """Return a modality that is *not* the one that just failed.

        This enforces SOUL.md's foundational rule. The engagement loop
        must call this — not `recommend_modality` directly — when
        handling a failed check.
        """
        chosen = self._calibrator.recommend_modality(profile, exclude=failed_modality)
        if chosen is failed_modality:
            raise RuntimeError(
                "modality rotation invariant violated: "
                f"rotator returned the excluded modality {failed_modality}"
            )
        return chosen

    def next_of_same_kind(
        self,
        profile: LearnerProfile,
    ) -> Modality:
        """Pick a modality to continue a session that is going well.

        This is a plain delegate to the calibrator for now; kept as a
        named method because the session runner reads more clearly when
        it calls `next_of_same_kind` vs `rotate_after_failure`.
        """
        return self._calibrator.recommend_modality(profile)

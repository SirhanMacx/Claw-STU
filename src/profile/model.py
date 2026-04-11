"""Learner profile data structures.

The learner profile is the Claw-STU equivalent of Claw-ED's pedagogical
fingerprint. It is the source of truth for how the agent adapts to a
particular student.

Design notes
------------
- Observational, not self-reported. Every field here should be derivable
  from interaction events, not from a form the student filled out.
- Domain-scoped. A learner's ZPD, misconceptions, and pacing are tracked
  per-domain (US History, Global History, etc.), not as global scalars.
- Portable. The profile must serialize to JSON and round-trip losslessly.
- Not a label. These structures describe current state, not identity.

None of this module imports from higher layers. It depends only on the
Python standard library and Pydantic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgeBracket(str, Enum):
    """Coarse age brackets used for content gating and voice calibration.

    We intentionally avoid storing an exact age. The bracket is what the
    agent needs to make safety and complexity decisions.
    """

    EARLY_ELEMENTARY = "early_elementary"   # ~5-7
    LATE_ELEMENTARY = "late_elementary"     # ~8-10
    MIDDLE = "middle"                       # ~11-13
    EARLY_HIGH = "early_high"               # ~14-15
    LATE_HIGH = "late_high"                 # ~16-18
    ADULT = "adult"                         # 18+

    @classmethod
    def from_age(cls, age: int) -> AgeBracket:
        """Map an integer age to a bracket. Raises on nonsense input."""
        if age < 0 or age > 120:
            raise ValueError(f"age out of range: {age}")
        if age <= 7:
            return cls.EARLY_ELEMENTARY
        if age <= 10:
            return cls.LATE_ELEMENTARY
        if age <= 13:
            return cls.MIDDLE
        if age <= 15:
            return cls.EARLY_HIGH
        if age <= 17:
            return cls.LATE_HIGH
        return cls.ADULT


class Domain(str, Enum):
    """Knowledge domains. MVP focuses on history; others are placeholders
    so the data model doesn't need to change when new subjects land."""

    US_HISTORY = "us_history"
    GLOBAL_HISTORY = "global_history"
    CIVICS = "civics"
    ELA = "ela"
    SCIENCE = "science"
    MATH = "math"
    OTHER = "other"


class Modality(str, Enum):
    """Instructional modalities. Stuart rotates through these based on
    observed engagement and comprehension — the student does not pick."""

    TEXT_READING = "text_reading"
    PRIMARY_SOURCE = "primary_source"
    SOCRATIC_DIALOGUE = "socratic_dialogue"
    INTERACTIVE_SCENARIO = "interactive_scenario"
    VISUAL_SPATIAL = "visual_spatial"
    WORKED_EXAMPLE = "worked_example"
    INQUIRY_PROJECT = "inquiry_project"


class ComplexityTier(str, Enum):
    """Three-tier differentiation from the Danielson/NYS framework."""

    APPROACHING = "approaching"
    MEETING = "meeting"
    EXCEEDING = "exceeding"

    def stepped_up(self) -> ComplexityTier:
        if self is ComplexityTier.APPROACHING:
            return ComplexityTier.MEETING
        if self is ComplexityTier.MEETING:
            return ComplexityTier.EXCEEDING
        return ComplexityTier.EXCEEDING

    def stepped_down(self) -> ComplexityTier:
        if self is ComplexityTier.EXCEEDING:
            return ComplexityTier.MEETING
        if self is ComplexityTier.MEETING:
            return ComplexityTier.APPROACHING
        return ComplexityTier.APPROACHING


class EventKind(str, Enum):
    """Kinds of observed interaction events that update the profile."""

    CALIBRATION_ANSWER = "calibration_answer"
    CHECK_FOR_UNDERSTANDING = "check_for_understanding"
    MODALITY_ENGAGEMENT = "modality_engagement"
    VOLUNTARY_QUESTION = "voluntary_question"
    SESSION_START = "session_start"
    SESSION_CLOSE = "session_close"


class ObservationEvent(BaseModel):
    """A single observed interaction. Events are the atoms of the profile:
    every mutation to a `LearnerProfile` should be derivable from a stream
    of these."""

    model_config = ConfigDict(frozen=True)

    kind: EventKind
    domain: Domain
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    modality: Modality | None = None
    tier: ComplexityTier | None = None
    correct: bool | None = None
    latency_seconds: float | None = None
    concept: str | None = None
    notes: str | None = None


class ModalityOutcome(BaseModel):
    """Running record of how a student does with a given modality. These
    numbers drive modality rotation decisions."""

    attempts: int = 0
    successes: int = 0
    total_latency_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.successes / self.attempts

    @property
    def mean_latency(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.total_latency_seconds / self.attempts

    def record(self, *, correct: bool, latency_seconds: float | None) -> None:
        self.attempts += 1
        if correct:
            self.successes += 1
        if latency_seconds is not None:
            self.total_latency_seconds += latency_seconds


class ZPDEstimate(BaseModel):
    """Per-domain ZPD estimate. Expressed as a current tier plus a
    confidence score in [0, 1]. Confidence is low on day one and rises
    as more evidence accumulates."""

    domain: Domain
    tier: ComplexityTier = ComplexityTier.MEETING
    confidence: float = 0.0
    samples: int = 0
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LearnerProfile(BaseModel):
    """The learner profile. Owned by the student. Portable. Observational.

    Not a gradebook. Not a diagnosis. Not a label. It is what Stuart needs
    to know in order to adapt.
    """

    model_config = ConfigDict(validate_assignment=True)

    learner_id: str
    age_bracket: AgeBracket
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    modality_outcomes: dict[Modality, ModalityOutcome] = Field(default_factory=dict)
    zpd_by_domain: dict[Domain, ZPDEstimate] = Field(default_factory=dict)
    misconceptions: dict[str, int] = Field(default_factory=dict)
    voluntary_question_count: int = 0
    events: list[ObservationEvent] = Field(default_factory=list)

    def outcome_for(self, modality: Modality) -> ModalityOutcome:
        """Return (creating if needed) the outcome tracker for a modality."""
        if modality not in self.modality_outcomes:
            self.modality_outcomes[modality] = ModalityOutcome()
        return self.modality_outcomes[modality]

    def zpd_for(self, domain: Domain) -> ZPDEstimate:
        """Return (creating if needed) the ZPD estimate for a domain."""
        if domain not in self.zpd_by_domain:
            self.zpd_by_domain[domain] = ZPDEstimate(domain=domain)
        return self.zpd_by_domain[domain]

    def record_event(self, event: ObservationEvent) -> None:
        """Append an observation event and bump `updated_at`. Downstream
        analysis (observer, ZPD calibrator) reads the event list."""
        self.events.append(event)
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Round-trippable dict representation for export."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearnerProfile:
        """Inverse of `to_dict`. Raises on malformed input."""
        return cls.model_validate(data)

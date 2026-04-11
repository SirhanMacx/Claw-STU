"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from clawstu.engagement.session import Session, SessionRunner
from clawstu.profile.model import Domain, LearnerProfile


@pytest.fixture
def runner() -> SessionRunner:
    return SessionRunner()


@pytest.fixture
def onboarded(runner: SessionRunner) -> tuple[LearnerProfile, Session]:
    profile, session = runner.onboard(
        learner_id="test-learner",
        age=15,
        domain=Domain.US_HISTORY,
    )
    return profile, session

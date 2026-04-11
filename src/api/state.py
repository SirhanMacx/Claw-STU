"""In-memory state for the MVP API.

This is intentionally simple: a single process-local dictionary that
maps `session_id` to `(profile, session)` tuples. It is *not* a
persistence layer. For local development and the first MVP demo it is
enough; for any real deployment, this is replaced by SQLite or a real
database before the guardian dashboard ships.

Everything in here is private to `src.api`. No other module should
import from this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from src.engagement.session import Session, SessionRunner
from src.profile.model import LearnerProfile


@dataclass
class SessionBundle:
    profile: LearnerProfile
    session: Session


@dataclass
class AppState:
    runner: SessionRunner = field(default_factory=SessionRunner)
    sessions: dict[str, SessionBundle] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def put(self, bundle: SessionBundle) -> None:
        with self.lock:
            self.sessions[bundle.session.id] = bundle

    def get(self, session_id: str) -> SessionBundle:
        with self.lock:
            if session_id not in self.sessions:
                raise KeyError(f"unknown session: {session_id}")
            return self.sessions[session_id]

    def drop(self, session_id: str) -> None:
        with self.lock:
            self.sessions.pop(session_id, None)


_APP_STATE = AppState()


def get_state() -> AppState:
    """Return the process-local app state.

    FastAPI dependency-injects this. Tests can replace the global
    state by constructing their own `AppState` and passing it in
    directly, but for the MVP the shared instance is sufficient.
    """
    return _APP_STATE

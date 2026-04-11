"""FastAPI app entry point.

Run locally with:

    uvicorn clawstu.api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI

from clawstu import __version__
from clawstu.api import admin, profile, session


def create_app() -> FastAPI:
    app = FastAPI(
        title="Claw-STU",
        description="Stuart — a personal learning agent that grows with the student.",
        version=__version__,
    )
    app.include_router(session.router)
    app.include_router(profile.router)
    app.include_router(admin.router)
    return app


app = create_app()

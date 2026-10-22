"""FastAPI application entry point: `uvicorn chesscoach.api.main:app`."""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from chesscoach import __version__
from chesscoach.api.routes import (
    analysis,
    auth,
    coaching,
    cohort,
    exercises,
    games,
    health,
    mistakes,
    plans,
    profiles,
    puzzles,
    students,
    weaknesses,
)
from chesscoach.core.config import get_settings
from chesscoach.core.errors import DomainError

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    settings.check_security()
    app = FastAPI(title="ChessMentor AI", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, no cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(students.router, prefix=API_PREFIX)
    app.include_router(games.router, prefix=API_PREFIX)
    app.include_router(analysis.router, prefix=API_PREFIX)
    app.include_router(weaknesses.router, prefix=API_PREFIX)
    app.include_router(profiles.router, prefix=API_PREFIX)
    app.include_router(coaching.router, prefix=API_PREFIX)
    app.include_router(exercises.router, prefix=API_PREFIX)
    app.include_router(cohort.router, prefix=API_PREFIX)
    app.include_router(mistakes.router, prefix=API_PREFIX)
    app.include_router(puzzles.router, prefix=API_PREFIX)
    app.include_router(plans.router, prefix=API_PREFIX)
    return app


app = create_app()

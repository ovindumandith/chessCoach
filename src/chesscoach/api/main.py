"""FastAPI application entry point: `uvicorn chesscoach.api.main:app`."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from chesscoach import __version__
from chesscoach.api.routes import games, health, students
from chesscoach.core.config import get_settings
from chesscoach.core.errors import DomainError

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title="ChessMentor AI", version=__version__)

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(students.router, prefix=API_PREFIX)
    app.include_router(games.router, prefix=API_PREFIX)
    return app


app = create_app()

"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.db import build_database
from app.providers.video.factory import build_video_provider
from app.routers import (
    admin,
    assignments,
    dev,
    enrollments,
    health,
    mfa,
    progress,
    quizzes,
    video,
)
from app.security.ratelimit import InMemoryRateLimiter, Limits, NullRateLimiter

logger = logging.getLogger("lms")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    database = build_database(settings)
    await database.connect()
    app.state.database = database
    app.state.video_provider = build_video_provider(settings)
    logger.info(
        "started", extra={"environment": settings.environment, "video": settings.video_provider}
    )
    try:
        yield
    finally:
        await database.disconnect()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="LMS API",
        version="0.1.0",
        lifespan=lifespan,
        # The interactive docs enumerate every route and schema. Useful in
        # development, an invitation in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    limits = Limits()
    app.state.rate_limits = limits
    app.state.rate_limit_window = limits.window_seconds
    app.state.rate_limiter = (
        InMemoryRateLimiter() if settings.rate_limit_enabled else NullRateLimiter()
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        # Without this the browser hides these from JavaScript entirely. Only a
        # short list of response headers is readable cross-origin by default, and
        # none of ours is on it -- so a 429 would arrive with no way to know how
        # long to wait, and a second-factor refusal with no way to know which
        # screen to show. The failure is invisible: the header is on the wire and
        # in curl, and `response.headers.get(...)` returns null anyway.
        expose_headers=[
            "Retry-After",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-MFA-Status",
        ],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return none of it: stack traces and driver errors
        # carry table names, hostnames and occasionally credentials.
        logger.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "internal server error"},
        )

    prefix = settings.api_base_path
    app.include_router(health.router)
    app.include_router(admin.router, prefix=prefix)
    # Its own router rather than a route in admin.py, because admin.py applies
    # the full second-factor gate to everything in it. /admin/mfa deliberately
    # sits behind a role-only check: an admin who is blocked has to be able to
    # find out why. No path collides with admin.router's own routes.
    app.include_router(mfa.router, prefix=prefix)
    if settings.video_provider == "mock":
        # Never reachable in production: Settings refuses to start there on the
        # mock provider at all.
        app.include_router(dev.router, prefix=prefix)
    app.include_router(assignments.router, prefix=prefix)
    app.include_router(enrollments.router, prefix=prefix)
    app.include_router(video.router, prefix=prefix)
    app.include_router(progress.router, prefix=prefix)
    app.include_router(quizzes.router, prefix=prefix)
    return app


app = create_app()

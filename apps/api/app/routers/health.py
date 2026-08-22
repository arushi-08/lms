"""Liveness and readiness.

Split deliberately: Render restarts on a failing liveness probe, which is the
wrong response to a database blip. Liveness answers "is this process alive",
readiness answers "can it serve traffic".
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.security.deps import DatabaseDep, SettingsDep

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(
    database: DatabaseDep, settings: SettingsDep, response: Response
) -> dict[str, object]:
    checks: dict[str, object] = {"video_provider": settings.video_provider}
    try:
        async with database.acquire() as conn:
            await conn.fetchval("select 1")
        checks["database"] = "ok"
    except Exception:
        # No exception text: readiness output is often public and connection
        # errors carry hostnames and usernames.
        checks["database"] = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks

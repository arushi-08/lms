"""Liveness and readiness.

Split deliberately: Render restarts on a failing liveness probe, which is the
wrong response to a database blip. Liveness answers "is this process alive",
readiness answers "can it serve traffic".
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.security.deps import DatabaseDep, SettingsDep

router = APIRouter(tags=["health"])

#: Every table the API queries. Checked at readiness so a database that is
#: reachable but behind on migrations reports *that*, instead of failing later
#: with an UndefinedTableError from whichever endpoint happens to be hit first.
EXPECTED_TABLES = (
    "profiles",
    "courses",
    "modules",
    "lessons",
    "enrollments",
    "lesson_progress",
    "quizzes",
    "quiz_questions",
    "quiz_options",
    "quiz_attempts",
    "quiz_responses",
    "assignments",
    "assignment_submissions",
    "certificates",
    "payments",
    "provider_events",
    "video_playback_sessions",
    "audit_log",
    "notifications",
)


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
            present = {
                row["table_name"]
                for row in await conn.fetch(
                    "select table_name from information_schema.tables "
                    "where table_schema = 'public'"
                )
            }
        checks["database"] = "ok"

        missing = [name for name in EXPECTED_TABLES if name not in present]
        if missing:
            # Table names are not sensitive, and naming them turns "something
            # is broken" into "run your migrations".
            checks["schema"] = "out of date"
            checks["missing_tables"] = missing
            checks["hint"] = "run `supabase db push` to apply pending migrations"
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            checks["schema"] = "ok"
    except Exception:
        # No exception text: readiness output is often public and connection
        # errors carry hostnames and usernames.
        checks["database"] = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks

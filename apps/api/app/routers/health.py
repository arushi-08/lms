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

#: Columns added by a migration that adds no table of its own.
#:
#: A table-only drift check cannot see those, and the way that failed was
#: exactly backwards: /readyz reported the schema healthy while a student
#: pressing play got an UndefinedColumnError from deep inside a query. A
#: migration that adds a column to an existing table belongs here, or the next
#: one will be found the same way.
EXPECTED_COLUMNS = (
    ("profiles", "mfa_factor_id"),          # 0012
    ("profiles", "mfa_verified_factors"),   # 0012
    ("profiles", "mfa_verified_at"),        # 0012
    ("lessons", "duration_seconds"),        # 0003
    ("assignments", "passing_score"),       # 0011
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
            columns = {
                (row["table_name"], row["column_name"])
                for row in await conn.fetch(
                    "select table_name, column_name from information_schema.columns "
                    "where table_schema = 'public'"
                )
            }
        checks["database"] = "ok"

        missing = [name for name in EXPECTED_TABLES if name not in present]
        # Only worth reporting for tables that exist: every column of a missing
        # table is missing too, and listing them buries the one fact that matters.
        missing_columns = [
            f"{table}.{column}"
            for table, column in EXPECTED_COLUMNS
            if table in present and (table, column) not in columns
        ]

        if missing or missing_columns:
            # Names are not sensitive, and naming them turns "something is
            # broken" into "run your migrations".
            checks["schema"] = "out of date"
            if missing:
                checks["missing_tables"] = missing
            if missing_columns:
                checks["missing_columns"] = missing_columns
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

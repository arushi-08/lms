"""Progress heartbeats.

The client reports how much it thinks has been watched; the server decides how
much to believe. See ``app.domain.progress`` for why the allowance is shaped the
way it is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.domain import progress as domain
from app.repositories import learning
from app.security.deps import CurrentUserDep, DatabaseDep, resolve_entitlement

router = APIRouter(prefix="/lessons", tags=["progress"])


class HeartbeatRequest(BaseModel):
    # Bounded so a nonsense value is rejected at the edge rather than clamped
    # deep in the domain. 24h of content in one lesson is not a real case.
    watched_seconds: int = Field(ge=0, le=86_400)
    position_seconds: int = Field(ge=0, le=86_400)


class ProgressResponse(BaseModel):
    lesson_id: UUID
    watched_seconds: int
    last_position_seconds: int
    completed: bool
    course_progress_percent: float
    course_completed: bool


@router.post("/{lesson_id}/progress", response_model=ProgressResponse)
async def record_progress(
    lesson_id: UUID,
    payload: HeartbeatRequest,
    user: CurrentUserDep,
    database: DatabaseDep,
) -> ProgressResponse:
    now = datetime.now(UTC)

    async with database.transaction() as conn:
        entitlement = await resolve_entitlement(
            conn, lesson_id=lesson_id, user=user, require_enrollment=True
        )
        context = entitlement.context

        if context.enrollment_id is None:
            # Admins previewing a course they are not enrolled in have nowhere
            # to hang progress, and should not accumulate any.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="no enrolment to record against"
            )

        stored = await learning.get_progress(conn, user.user_id, lesson_id)
        state = domain.ProgressState(
            watched_seconds=stored.watched_seconds if stored else 0,
            last_position_seconds=stored.last_position_seconds if stored else 0,
            completed=stored.completed if stored else False,
            completed_at=stored.completed_at if stored else None,
            last_heartbeat_at=stored.last_heartbeat_at if stored else None,
        )

        update = domain.apply_heartbeat(
            state,
            domain.Heartbeat(
                watched_seconds=payload.watched_seconds,
                position_seconds=payload.position_seconds,
                at=now,
            ),
            duration_seconds=context.duration_seconds,
            threshold_percent=context.completion_threshold,
        )

        await learning.upsert_progress(
            conn,
            user_id=user.user_id,
            lesson_id=lesson_id,
            enrollment_id=context.enrollment_id,
            watched_seconds=update.watched_seconds,
            last_position_seconds=update.last_position_seconds,
            completed=update.completed,
            completed_at=update.completed_at,
            last_heartbeat_at=update.last_heartbeat_at,
        )

        counts = await learning.get_completion_counts(conn, context.course_id, user.user_id)
        percent = domain.course_progress_percent(counts.required_total, counts.required_completed)
        course_done = domain.is_course_complete(
            required_total=counts.required_total,
            required_completed=counts.required_completed,
            quizzes_total=counts.quizzes_total,
            quizzes_passed=counts.quizzes_passed,
        )

        await learning.update_enrollment_progress(
            conn,
            enrollment_id=context.enrollment_id,
            progress_percent=percent,
            completed=course_done,
            last_lesson_id=lesson_id,
        )

    return ProgressResponse(
        lesson_id=lesson_id,
        watched_seconds=update.watched_seconds,
        last_position_seconds=update.last_position_seconds,
        completed=update.completed,
        course_progress_percent=percent,
        course_completed=course_done,
    )

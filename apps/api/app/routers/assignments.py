"""Assignments: the half of assessment a machine cannot mark.

Students submit; admins grade. The split matters — every write that carries a
score lives behind require_admin, and a student's only write is a submission of
their own work.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.repositories import admin as admin_repo
from app.repositories import assessment as repo
from app.repositories import learning
from app.security.deps import AdminDep, CurrentUserDep, DatabaseDep, resolve_entitlement
from app.services import completion

router = APIRouter(tags=["assignments"])


class SubmitRequest(BaseModel):
    text_answer: str | None = Field(default=None, max_length=50_000)
    link_url: HttpUrl | None = None

    @model_validator(mode="after")
    def _has_content(self) -> SubmitRequest:
        # The database enforces this too, but a 422 naming the problem beats a
        # 500 from a check constraint.
        if not (self.text_answer and self.text_answer.strip()) and self.link_url is None:
            raise ValueError("provide written work or a link")
        return self


class GradeRequest(BaseModel):
    score: float = Field(ge=0, le=100)
    feedback: str | None = Field(default=None, max_length=10_000)


# ---------------------------------------------------------------- students --

@router.get("/lessons/{lesson_id}/assignment")
async def get_assignment(
    lesson_id: UUID, user: CurrentUserDep, database: DatabaseDep
) -> dict[str, Any]:
    """The brief, plus this student's own submission history."""
    async with database.acquire() as conn:
        await resolve_entitlement(
            conn, lesson_id=lesson_id, user=user, require_enrollment=True
        )
        assignment = await repo.get_assignment_by_lesson(conn, lesson_id)
        if assignment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="no assignment on this lesson"
            )
        submissions = await repo.list_submissions_for_user(
            conn, assignment.assignment_id, user.user_id
        )

    return {
        "assignment_id": str(assignment.assignment_id),
        "lesson_id": str(assignment.lesson_id),
        "title": assignment.title,
        "instructions": assignment.instructions,
        "max_points": assignment.max_points,
        "passing_score": assignment.passing_score,
        "is_graded": assignment.is_graded,
        "allow_text": assignment.allow_text,
        "allow_link": assignment.allow_link,
        "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
        "allow_late": assignment.allow_late,
        "submissions": submissions,
    }


@router.post("/assignments/{assignment_id}/submissions", status_code=status.HTTP_201_CREATED)
async def submit(
    assignment_id: UUID,
    payload: SubmitRequest,
    user: CurrentUserDep,
    database: DatabaseDep,
) -> dict[str, Any]:
    async with database.transaction() as conn:
        assignment = await repo.get_assignment(conn, assignment_id)
        if assignment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="assignment not found"
            )
        # Entitlement is checked against the lesson, so assignment access follows
        # exactly the same rule as the rest of the course.
        await resolve_entitlement(
            conn, lesson_id=assignment.lesson_id, user=user, require_enrollment=True
        )

        if payload.link_url is not None and not assignment.allow_link:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="this assignment does not accept links",
            )
        if payload.text_answer and not assignment.allow_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="this assignment does not accept written answers",
            )

        try:
            submission = await repo.create_submission(
                conn,
                assignment=assignment,
                user_id=user.user_id,
                text_answer=payload.text_answer,
                link_url=str(payload.link_url) if payload.link_url else None,
            )
        except repo.ConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

        # An ungraded assignment is finished by handing it in -- there is no
        # grade coming, so waiting for one would strand the lesson forever.
        if not assignment.is_graded:
            context = await learning.get_lesson_context(
                conn, assignment.lesson_id, user.user_id
            )
            if context and context.enrollment_id:
                await learning.mark_lesson_complete(
                    conn,
                    user_id=user.user_id,
                    lesson_id=assignment.lesson_id,
                    enrollment_id=context.enrollment_id,
                    now=datetime.now(UTC),
                )
                await completion.recompute(
                    conn,
                    course_id=assignment.course_id,
                    user_id=user.user_id,
                    enrollment_id=context.enrollment_id,
                    last_lesson_id=assignment.lesson_id,
                )

    return {**submission, "id": str(submission["id"])}


# ------------------------------------------------------------------ admins --

@router.get("/admin/submissions")
async def grading_queue(
    admin: AdminDep,
    database: DatabaseDep,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
    only_ungraded: bool = True,
) -> list[dict[str, Any]]:
    async with database.acquire() as conn:
        return await repo.list_grading_queue(
            conn, limit=limit, offset=offset, only_ungraded=only_ungraded
        )


@router.post("/admin/submissions/{submission_id}/grade")
async def grade(
    submission_id: UUID,
    payload: GradeRequest,
    request: Request,
    admin: AdminDep,
    database: DatabaseDep,
) -> dict[str, Any]:
    async with database.transaction() as conn:
        try:
            result = await repo.grade_submission(
                conn,
                submission_id=submission_id,
                grader_id=admin.user_id,
                score=payload.score,
                feedback=payload.feedback,
            )
        except repo.ConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc

        # A passing grade finishes the lesson for that student, and their
        # course standing moves without them reloading anything.
        if result["passed"]:
            assignment = await repo.get_assignment(conn, result["assignment_id"])
            if assignment is not None:
                context = await learning.get_lesson_context(
                    conn, assignment.lesson_id, result["user_id"]
                )
                if context and context.enrollment_id:
                    await learning.mark_lesson_complete(
                        conn,
                        user_id=result["user_id"],
                        lesson_id=assignment.lesson_id,
                        enrollment_id=context.enrollment_id,
                        now=datetime.now(UTC),
                    )
                    await completion.recompute(
                        conn,
                        course_id=assignment.course_id,
                        user_id=result["user_id"],
                        enrollment_id=context.enrollment_id,
                    )

        await admin_repo.write_audit(
            conn,
            actor_id=admin.user_id,
            action="submission.grade",
            entity_type="assignment_submission",
            entity_id=str(submission_id),
            diff={"score": payload.score, "passed": result["passed"]},
            ip=request.client.host if request.client else None,
        )

    return {
        "id": str(result["id"]),
        "score": float(result["score"]),
        "passed": result["passed"],
        "status": result["status"],
    }

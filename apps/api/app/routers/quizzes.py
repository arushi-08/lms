"""Quiz delivery and submission.

Grading happens here, on the server, against the key loaded with the service
role. The answer key is never sent to the client -- not hidden in the payload,
not filtered out in the UI. The read path physically cannot return it because
``get_student_questions`` does not select those columns, and RLS denies the
browser's own credentials any access to them.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.domain import grading
from app.domain.progress import course_progress_percent, is_course_complete
from app.repositories import learning
from app.security.deps import CurrentUserDep, DatabaseDep, resolve_entitlement

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


class QuizView(BaseModel):
    quiz_id: UUID
    lesson_id: UUID
    title: str
    passing_score: int
    max_attempts: int | None
    time_limit_seconds: int | None
    attempts_used: int
    attempts_remaining: int | None
    questions: list[dict[str, Any]]


class SubmittedResponse(BaseModel):
    question_id: UUID
    selected_option_ids: list[UUID] = Field(default_factory=list, max_length=50)
    text_answer: str | None = Field(default=None, max_length=2000)


class SubmitRequest(BaseModel):
    responses: list[SubmittedResponse] = Field(default_factory=list, max_length=500)


class GradedQuestion(BaseModel):
    question_id: UUID
    is_correct: bool
    points_awarded: int


class AttemptResultView(BaseModel):
    attempt_id: UUID
    attempt_number: int
    score: float
    passed: bool
    points_earned: int
    points_possible: int
    results: list[GradedQuestion]
    course_progress_percent: float
    course_completed: bool


async def _load_quiz_for_user(conn: Any, quiz_id: UUID, user: Any) -> learning.QuizMeta:
    meta = await learning.get_quiz_meta(conn, quiz_id)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quiz not found")
    # Entitlement is checked against the quiz's lesson, so quiz access follows
    # exactly the same rule as the rest of the course.
    await resolve_entitlement(conn, lesson_id=meta.lesson_id, user=user, require_enrollment=True)
    return meta


@router.get("/{quiz_id}", response_model=QuizView)
async def get_quiz(quiz_id: UUID, user: CurrentUserDep, database: DatabaseDep) -> QuizView:
    async with database.acquire() as conn:
        meta = await _load_quiz_for_user(conn, quiz_id, user)
        questions = await learning.get_student_questions(conn, quiz_id)
        used = await learning.count_attempts(conn, quiz_id, user.user_id)

    remaining = None if meta.max_attempts is None else max(0, meta.max_attempts - used)
    return QuizView(
        quiz_id=meta.quiz_id,
        lesson_id=meta.lesson_id,
        title=meta.title,
        passing_score=meta.passing_score,
        max_attempts=meta.max_attempts,
        time_limit_seconds=meta.time_limit_seconds,
        attempts_used=used,
        attempts_remaining=remaining,
        questions=questions,
    )


@router.post("/{quiz_id}/attempts", response_model=AttemptResultView)
async def submit_attempt(
    quiz_id: UUID,
    payload: SubmitRequest,
    user: CurrentUserDep,
    database: DatabaseDep,
) -> AttemptResultView:
    async with database.transaction() as conn:
        meta = await _load_quiz_for_user(conn, quiz_id, user)

        used = await learning.count_attempts(conn, quiz_id, user.user_id)
        if meta.max_attempts is not None and used >= meta.max_attempts:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="no attempts remaining"
            )

        questions = await learning.get_answer_key(conn, quiz_id)
        if not questions:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="quiz has no questions"
            )

        result = grading.grade_attempt(
            questions,
            [
                grading.Response(
                    question_id=r.question_id,
                    selected_option_ids=frozenset(r.selected_option_ids),
                    text_answer=r.text_answer,
                )
                for r in payload.responses
            ],
            passing_score=meta.passing_score,
        )

        attempt_id = await learning.create_graded_attempt(
            conn,
            quiz_id=quiz_id,
            user_id=user.user_id,
            attempt_number=used + 1,
            score=float(result.score),
            passed=result.passed,
            responses=[
                {
                    "question_id": g.question_id,
                    "selected_option_ids": list(g.selected_option_ids),
                    "text_answer": g.text_answer,
                    "is_correct": g.is_correct,
                    "points_awarded": g.points_awarded,
                }
                for g in result.responses
            ],
        )

        counts = await learning.get_completion_counts(conn, meta.course_id, user.user_id)
        percent = course_progress_percent(counts.required_total, counts.required_completed)
        course_done = is_course_complete(
            required_total=counts.required_total,
            required_completed=counts.required_completed,
            quizzes_total=counts.quizzes_total,
            quizzes_passed=counts.quizzes_passed,
        )

        context = await learning.get_lesson_context(conn, meta.lesson_id, user.user_id)
        if context and context.enrollment_id:
            await learning.update_enrollment_progress(
                conn,
                enrollment_id=context.enrollment_id,
                progress_percent=percent,
                completed=course_done,
                last_lesson_id=meta.lesson_id,
            )

    return AttemptResultView(
        attempt_id=attempt_id,
        attempt_number=used + 1,
        score=float(result.score),
        passed=result.passed,
        points_earned=result.points_earned,
        points_possible=result.points_possible,
        # Per-question correctness only. Which option *was* right is not
        # returned, so an unlimited-retry quiz cannot be walked to the answers
        # one submission at a time.
        results=[
            GradedQuestion(
                question_id=g.question_id,
                is_correct=g.is_correct,
                points_awarded=g.points_awarded,
            )
            for g in result.responses
        ],
        course_progress_percent=percent,
        course_completed=course_done,
    )

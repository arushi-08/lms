"""SQL for assignments: the definition, submissions, and grading.

Assignments are the half of assessment a machine cannot mark. The rules that
matter are about *who* may write what: a student may submit, and nothing else.
Scores, verdicts and feedback are written only by grading routes, which sit
behind require_admin.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

Conn = asyncpg.Connection


class ConflictError(Exception):
    """Coherent request, but the data will not allow it."""


@dataclass(frozen=True, slots=True)
class AssignmentMeta:
    assignment_id: UUID
    lesson_id: UUID
    course_id: UUID
    title: str
    instructions: str
    max_points: int
    passing_score: int
    is_graded: bool
    allow_text: bool
    allow_link: bool
    due_at: datetime | None
    allow_late: bool


async def get_assignment_by_lesson(conn: Conn, lesson_id: UUID) -> AssignmentMeta | None:
    row = await conn.fetchrow(
        """
        select a.id as assignment_id, a.lesson_id, m.course_id, a.title, a.instructions,
               a.max_points, a.passing_score, a.is_graded, a.allow_text, a.allow_link,
               a.due_at, a.allow_late
        from assignments a
        join lessons l on l.id = a.lesson_id
        join modules m on m.id = l.module_id
        where a.lesson_id = $1
        """,
        lesson_id,
    )
    return AssignmentMeta(**dict(row)) if row else None


async def get_assignment(conn: Conn, assignment_id: UUID) -> AssignmentMeta | None:
    row = await conn.fetchrow(
        """
        select a.id as assignment_id, a.lesson_id, m.course_id, a.title, a.instructions,
               a.max_points, a.passing_score, a.is_graded, a.allow_text, a.allow_link,
               a.due_at, a.allow_late
        from assignments a
        join lessons l on l.id = a.lesson_id
        join modules m on m.id = l.module_id
        where a.id = $1
        """,
        assignment_id,
    )
    return AssignmentMeta(**dict(row)) if row else None


async def list_submissions_for_user(
    conn: Conn, assignment_id: UUID, user_id: UUID
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        select id, attempt_number, text_answer, link_url, status::text as status,
               submitted_at, is_late, score, passed, feedback, graded_at
        from assignment_submissions
        where assignment_id = $1 and user_id = $2
        order by attempt_number desc
        """,
        assignment_id,
        user_id,
    )
    return [dict(row) for row in rows]


async def create_submission(
    conn: Conn,
    *,
    assignment: AssignmentMeta,
    user_id: UUID,
    text_answer: str | None,
    link_url: str | None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    is_late = assignment.due_at is not None and now > assignment.due_at
    if is_late and not assignment.allow_late:
        raise ConflictError("the deadline for this assignment has passed")

    # A new attempt rather than an edit: the student needs to keep seeing the
    # work the feedback was written about.
    next_attempt = (
        await conn.fetchval(
            "select coalesce(max(attempt_number), 0) + 1 from assignment_submissions "
            "where assignment_id = $1 and user_id = $2",
            assignment.assignment_id,
            user_id,
        )
        or 1
    )

    row = await conn.fetchrow(
        """
        insert into assignment_submissions
            (assignment_id, user_id, attempt_number, text_answer, link_url, is_late)
        values ($1, $2, $3, $4, $5, $6)
        returning id, attempt_number, status::text as status, submitted_at, is_late
        """,
        assignment.assignment_id,
        user_id,
        next_attempt,
        text_answer,
        link_url,
        is_late,
    )
    return dict(row)


async def list_grading_queue(
    conn: Conn, *, limit: int, offset: int, only_ungraded: bool
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        select s.id, s.attempt_number, s.status::text as status, s.submitted_at, s.is_late,
               s.text_answer, s.link_url, s.score, s.passed, s.feedback,
               p.id as user_id, p.email, p.full_name,
               a.id as assignment_id, a.title as assignment_title,
               a.max_points, a.passing_score,
               c.title as course_title, c.slug as course_slug
        from assignment_submissions s
        join profiles p    on p.id = s.user_id
        join assignments a on a.id = s.assignment_id
        join lessons l     on l.id = a.lesson_id
        join modules m     on m.id = l.module_id
        join courses c     on c.id = m.course_id
        where ($3::boolean is false or s.status = 'submitted')
        order by s.submitted_at
        limit $1 offset $2
        """,
        limit,
        offset,
        only_ungraded,
    )
    return [dict(row) for row in rows]


async def grade_submission(
    conn: Conn,
    *,
    submission_id: UUID,
    grader_id: UUID,
    score: float,
    feedback: str | None,
) -> dict[str, Any]:
    assignment = await conn.fetchrow(
        """
        select a.passing_score, s.user_id, a.id as assignment_id
        from assignment_submissions s
        join assignments a on a.id = s.assignment_id
        where s.id = $1
        """,
        submission_id,
    )
    if assignment is None:
        raise ConflictError("submission not found")

    # Pass/fail is derived from the score and the assignment's threshold, never
    # sent by the grader. Otherwise the two could disagree, and the certificate
    # rule reads `passed`.
    passed = score >= assignment["passing_score"]

    row = await conn.fetchrow(
        """
        update assignment_submissions
           set score = $2, passed = $3, feedback = $4, status = 'graded',
               graded_by = $5, graded_at = now()
         where id = $1
        returning id, score, passed, status::text as status, graded_at
        """,
        submission_id,
        score,
        passed,
        feedback,
        grader_id,
    )
    return {**dict(row), "user_id": assignment["user_id"]}

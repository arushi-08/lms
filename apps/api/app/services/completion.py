"""Recomputing where a student stands in a course.

Every path that can complete a lesson -- a watch heartbeat, a passing quiz
attempt, a passing assignment grade -- ends here, so the percentage and the
course-complete verdict are derived in exactly one place. Three copies of this
arithmetic would eventually disagree, and the one that disagrees is the one
that issues a certificate.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.progress import course_progress_percent, is_course_complete
from app.repositories import learning


@dataclass(frozen=True, slots=True)
class CourseStanding:
    progress_percent: float
    course_completed: bool


async def recompute(
    conn: object,
    *,
    course_id: UUID,
    user_id: UUID,
    enrollment_id: UUID,
    last_lesson_id: UUID | None = None,
) -> CourseStanding:
    counts = await learning.get_completion_counts(conn, course_id, user_id)  # type: ignore[arg-type]

    percent = course_progress_percent(counts.required_total, counts.required_completed)
    completed = is_course_complete(
        required_total=counts.required_total,
        required_completed=counts.required_completed,
        quizzes_total=counts.quizzes_total,
        quizzes_passed=counts.quizzes_passed,
        graded_assignments_total=counts.graded_assignments_total,
        graded_assignments_passed=counts.graded_assignments_passed,
    )

    await learning.update_enrollment_progress(
        conn,  # type: ignore[arg-type]
        enrollment_id=enrollment_id,
        progress_percent=percent,
        completed=completed,
        last_lesson_id=last_lesson_id,
    )
    return CourseStanding(progress_percent=percent, course_completed=completed)

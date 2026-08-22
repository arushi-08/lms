"""SQL for the learning paths: entitlement, playback, progress, assessment.

Explicit SQL rather than an ORM. The migrations are the schema's source of
truth, and a parallel set of ORM models would be a second definition free to
drift from them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.domain.grading import Question, QuestionType

# asyncpg's Connection is not subscriptable at runtime, so this alias stays bare.
Conn = asyncpg.Connection


@dataclass(frozen=True, slots=True)
class LessonContext:
    """Everything an entitlement decision needs, in one round trip."""

    lesson_id: UUID
    lesson_type: str
    is_preview: bool
    is_required: bool
    duration_seconds: int | None
    video_id: str | None
    video_status: str
    course_id: UUID
    course_status: str
    completion_threshold: int
    enrollment_id: UUID | None
    enrollment_status: str | None
    enrollment_expires_at: datetime | None

    @property
    def has_live_enrollment(self) -> bool:
        if self.enrollment_id is None or self.enrollment_status != "active":
            return False
        return self.enrollment_expires_at is None or self.enrollment_expires_at > _now()


def _now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


_LESSON_CONTEXT_SQL = """
select
    l.id                     as lesson_id,
    l.type::text             as lesson_type,
    l.is_preview,
    l.is_required,
    l.duration_seconds,
    l.video_id,
    l.video_status::text     as video_status,
    c.id                     as course_id,
    c.status::text           as course_status,
    c.completion_threshold,
    e.id                     as enrollment_id,
    e.status::text           as enrollment_status,
    e.expires_at             as enrollment_expires_at
from lessons  l
join modules  m on m.id = l.module_id
join courses  c on c.id = m.course_id
left join enrollments e on e.course_id = c.id and e.user_id = $2
where l.id = $1
"""


async def get_lesson_context(conn: Conn, lesson_id: UUID, user_id: UUID) -> LessonContext | None:
    row = await conn.fetchrow(_LESSON_CONTEXT_SQL, lesson_id, user_id)
    return LessonContext(**dict(row)) if row else None


async def get_profile_role(conn: Conn, user_id: UUID) -> str | None:
    """Authoritative role, read fresh.

    Admin routes call this rather than trusting the token's claim, so that
    revoking an admin takes effect immediately instead of at token expiry.
    """
    return await conn.fetchval("select role::text from profiles where id = $1", user_id)


# ----------------------------------------------------------------- playback --

async def count_live_playback_sessions(conn: Conn, user_id: UUID) -> int:
    return (
        await conn.fetchval(
            "select count(*) from video_playback_sessions "
            "where user_id = $1 and expires_at > now()",
            user_id,
        )
        or 0
    )


async def record_playback_session(
    conn: Conn,
    *,
    user_id: UUID,
    lesson_id: UUID,
    expires_at: datetime,
    ip: str | None,
    user_agent: str | None,
) -> UUID:
    return await conn.fetchval(  # type: ignore[no-any-return]
        "insert into video_playback_sessions (user_id, lesson_id, expires_at, ip, user_agent) "
        "values ($1, $2, $3, $4::inet, $5) returning id",
        user_id,
        lesson_id,
        expires_at,
        ip,
        (user_agent or "")[:500] or None,
    )


# ----------------------------------------------------------------- progress --

@dataclass(frozen=True, slots=True)
class StoredProgress:
    watched_seconds: int
    last_position_seconds: int
    completed: bool
    completed_at: datetime | None
    last_heartbeat_at: datetime | None


async def get_progress(conn: Conn, user_id: UUID, lesson_id: UUID) -> StoredProgress | None:
    row = await conn.fetchrow(
        "select watched_seconds, last_position_seconds, completed, completed_at, "
        "last_heartbeat_at from lesson_progress where user_id = $1 and lesson_id = $2",
        user_id,
        lesson_id,
    )
    return StoredProgress(**dict(row)) if row else None


async def upsert_progress(
    conn: Conn,
    *,
    user_id: UUID,
    lesson_id: UUID,
    enrollment_id: UUID,
    watched_seconds: int,
    last_position_seconds: int,
    completed: bool,
    completed_at: datetime | None,
    last_heartbeat_at: datetime,
) -> None:
    await conn.execute(
        """
        insert into lesson_progress (
            user_id, lesson_id, enrollment_id, watched_seconds, last_position_seconds,
            completed, completed_at, last_heartbeat_at
        ) values ($1, $2, $3, $4, $5, $6, $7, $8)
        on conflict (user_id, lesson_id) do update set
            watched_seconds       = excluded.watched_seconds,
            last_position_seconds = excluded.last_position_seconds,
            completed             = excluded.completed,
            completed_at          = excluded.completed_at,
            last_heartbeat_at     = excluded.last_heartbeat_at
        """,
        user_id,
        lesson_id,
        enrollment_id,
        watched_seconds,
        last_position_seconds,
        completed,
        completed_at,
        last_heartbeat_at,
    )


@dataclass(frozen=True, slots=True)
class CourseCompletionCounts:
    required_total: int
    required_completed: int
    quizzes_total: int
    quizzes_passed: int


_COMPLETION_COUNTS_SQL = """
with course_lessons as (
    select l.id, l.is_required
    from lessons l
    join modules m on m.id = l.module_id
    where m.course_id = $1
),
course_quizzes as (
    select q.id from quizzes q where q.lesson_id in (select id from course_lessons)
)
select
    (select count(*) from course_lessons where is_required)                   as required_total,
    (select count(*) from lesson_progress lp
      join course_lessons cl on cl.id = lp.lesson_id
      where lp.user_id = $2 and lp.completed and cl.is_required)              as required_completed,
    (select count(*) from course_quizzes)                                     as quizzes_total,
    (select count(distinct qa.quiz_id) from quiz_attempts qa
      where qa.user_id = $2 and qa.passed
        and qa.quiz_id in (select id from course_quizzes))                    as quizzes_passed
"""


async def get_completion_counts(
    conn: Conn, course_id: UUID, user_id: UUID
) -> CourseCompletionCounts:
    row = await conn.fetchrow(_COMPLETION_COUNTS_SQL, course_id, user_id)
    return CourseCompletionCounts(**dict(row))


async def update_enrollment_progress(
    conn: Conn,
    *,
    enrollment_id: UUID,
    progress_percent: float,
    completed: bool,
    last_lesson_id: UUID | None,
) -> None:
    await conn.execute(
        """
        update enrollments set
            progress_percent = $2,
            last_lesson_id   = coalesce($4, last_lesson_id),
            completed_at     = case
                                 when $3 and completed_at is null then now()
                                 else completed_at
                               end
        where id = $1
        """,
        enrollment_id,
        progress_percent,
        completed,
        last_lesson_id,
    )


# --------------------------------------------------------------- assessment --

@dataclass(frozen=True, slots=True)
class QuizMeta:
    quiz_id: UUID
    lesson_id: UUID
    course_id: UUID
    title: str
    passing_score: int
    max_attempts: int | None
    time_limit_seconds: int | None
    shuffle_questions: bool


async def get_quiz_meta(conn: Conn, quiz_id: UUID) -> QuizMeta | None:
    row = await conn.fetchrow(
        """
        select q.id as quiz_id, q.lesson_id, m.course_id, q.title, q.passing_score,
               q.max_attempts, q.time_limit_seconds, q.shuffle_questions
        from quizzes q
        join lessons l on l.id = q.lesson_id
        join modules m on m.id = l.module_id
        where q.id = $1
        """,
        quiz_id,
    )
    return QuizMeta(**dict(row)) if row else None


async def get_answer_key(conn: Conn, quiz_id: UUID) -> list[Question]:
    """Load questions *with* their answers. Service role only.

    The result of this call must never be serialised into a client response.
    Routes build the student-facing payload from ``get_student_questions``
    instead, which cannot return the key because it does not select it.
    """
    rows = await conn.fetch(
        """
        select qq.id, qq.type::text as type, qq.points, qq.correct_answers,
               coalesce(
                   array_agg(qo.id) filter (where qo.is_correct), '{}'
               ) as correct_option_ids
        from quiz_questions qq
        left join quiz_options qo on qo.question_id = qq.id
        where qq.quiz_id = $1
        group by qq.id
        order by qq.position
        """,
        quiz_id,
    )
    return [
        Question(
            id=row["id"],
            type=QuestionType(row["type"]),
            points=row["points"],
            correct_option_ids=frozenset(row["correct_option_ids"] or ()),
            correct_answers=tuple(row["correct_answers"] or ()),
        )
        for row in rows
    ]


async def get_student_questions(conn: Conn, quiz_id: UUID) -> list[dict[str, Any]]:
    """The question payload a student may see.

    Note what is absent from the select list: ``qo.is_correct`` and
    ``qq.correct_answers``. The key cannot leak through this function because
    it is never fetched, rather than fetched and then filtered -- filtering is
    the kind of thing a later refactor quietly drops.
    """
    rows = await conn.fetch(
        """
        select qq.id, qq.type::text as type, qq.prompt, qq.points, qq.position,
               coalesce(
                   jsonb_agg(
                       jsonb_build_object('id', qo.id, 'text', qo.text)
                       order by qo.position
                   ) filter (where qo.id is not null),
                   '[]'::jsonb
               ) as options
        from quiz_questions qq
        left join quiz_options qo on qo.question_id = qq.id
        where qq.quiz_id = $1
        group by qq.id
        order by qq.position
        """,
        quiz_id,
    )
    # asyncpg hands back jsonb as a string; decode it here so callers get a
    # list of dicts rather than a JSON blob that silently serialises twice.
    return [{**dict(row), "options": json.loads(row["options"])} for row in rows]


async def count_attempts(conn: Conn, quiz_id: UUID, user_id: UUID) -> int:
    return (
        await conn.fetchval(
            "select count(*) from quiz_attempts where quiz_id = $1 and user_id = $2",
            quiz_id,
            user_id,
        )
        or 0
    )


async def create_graded_attempt(
    conn: Conn,
    *,
    quiz_id: UUID,
    user_id: UUID,
    attempt_number: int,
    score: float,
    passed: bool,
    responses: list[dict[str, Any]],
) -> UUID:
    attempt_id: UUID = await conn.fetchval(
        """
        insert into quiz_attempts
            (quiz_id, user_id, attempt_number, submitted_at, score, passed)
        values ($1, $2, $3, now(), $4, $5)
        returning id
        """,
        quiz_id,
        user_id,
        attempt_number,
        score,
        passed,
    )

    await conn.executemany(
        """
        insert into quiz_responses
            (attempt_id, question_id, selected_option_ids, text_answer, is_correct, points_awarded)
        values ($1, $2, $3, $4, $5, $6)
        """,
        [
            (
                attempt_id,
                r["question_id"],
                r["selected_option_ids"],
                r["text_answer"],
                r["is_correct"],
                r["points_awarded"],
            )
            for r in responses
        ],
    )
    return attempt_id

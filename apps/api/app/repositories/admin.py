"""SQL for the admin surface: authoring, ordering, enrolment, audit.

Everything here runs with the service role, so the router's require_admin
dependency is the only thing standing between these functions and the public.
Nothing in this module re-checks permissions -- that would spread the decision
across two places and make it easy to satisfy neither.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg
from slugify import slugify

Conn = asyncpg.Connection


class ConflictError(Exception):
    """The request is coherent but the data will not allow it."""


# ------------------------------------------------------------------- audit --

async def write_audit(
    conn: Conn,
    *,
    actor_id: UUID,
    action: str,
    entity_type: str,
    entity_id: str | None,
    diff: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    await conn.execute(
        "insert into audit_log (actor_id, action, entity_type, entity_id, diff, ip) "
        "values ($1, $2, $3, $4, $5::jsonb, $6::inet)",
        actor_id,
        action,
        entity_type,
        entity_id,
        json.dumps(diff) if diff is not None else None,
        ip,
    )


# ----------------------------------------------------------------- courses --

async def unique_slug(conn: Conn, title: str, *, exclude_id: UUID | None = None) -> str:
    """Derive a URL slug, disambiguating collisions with a numeric suffix.

    Slugs are part of public URLs, so they must be stable and unique. Letting
    the database's unique constraint reject a duplicate would surface as a 500
    on an otherwise reasonable request.
    """
    base = slugify(title)[:60] or "course"
    candidate = base
    suffix = 2
    while True:
        existing = await conn.fetchval(
            "select id from courses where slug = $1 and ($2::uuid is null or id <> $2)",
            candidate,
            exclude_id,
        )
        if existing is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


async def list_courses(conn: Conn) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        select c.id, c.slug, c.title, c.subtitle, c.status::text as status,
               c.is_free, c.price_cents, c.currency, c.published_at, c.updated_at,
               (select count(*) from modules m where m.course_id = c.id) as module_count,
               (select count(*) from lessons l
                  join modules m on m.id = l.module_id
                 where m.course_id = c.id) as lesson_count,
               (select count(*) from enrollments e
                 where e.course_id = c.id and e.status = 'active') as student_count
        from courses c
        order by c.updated_at desc
        """
    )
    return [dict(row) for row in rows]


async def create_course(conn: Conn, *, title: str, created_by: UUID) -> dict[str, Any]:
    slug = await unique_slug(conn, title)
    row = await conn.fetchrow(
        """
        insert into courses (slug, title, status, created_by)
        values ($1, $2, 'draft', $3)
        returning id, slug, title, status::text as status
        """,
        slug,
        title,
        created_by,
    )
    return dict(row)


COURSE_UPDATABLE = {
    "title", "subtitle", "description", "thumbnail_url", "is_free", "price_cents",
    "currency", "tax_rate_bps", "access_type", "access_days", "completion_threshold",
}


async def update_course(conn: Conn, course_id: UUID, changes: dict[str, Any]) -> dict[str, Any]:
    # Allowlist rather than passing the payload through: without it, a client
    # could set status or published_at and publish a course by editing its title.
    fields = {k: v for k, v in changes.items() if k in COURSE_UPDATABLE}
    if not fields:
        row = await conn.fetchrow("select * from courses where id = $1", course_id)
        if row is None:
            raise ConflictError("course not found")
        return dict(row)

    assignments = ", ".join(f"{name} = ${i + 2}" for i, name in enumerate(fields))
    row = await conn.fetchrow(
        f"update courses set {assignments} where id = $1 returning *",
        course_id,
        *fields.values(),
    )
    if row is None:
        raise ConflictError("course not found")
    return dict(row)


async def set_course_status(conn: Conn, course_id: UUID, status: str) -> dict[str, Any]:
    if status == "published":
        # A course with nothing in it would appear in the catalog as an empty
        # shell, which is worse than not appearing at all.
        lesson_count = await conn.fetchval(
            "select count(*) from lessons l join modules m on m.id = l.module_id "
            "where m.course_id = $1",
            course_id,
        )
        if not lesson_count:
            raise ConflictError("a course needs at least one lesson before it can be published")

    row = await conn.fetchrow(
        """
        update courses
           set status = $2::content_status,
               published_at = case
                 when $2 = 'published' then coalesce(published_at, now())
                 else published_at
               end
         where id = $1
        returning id, slug, status::text as status, published_at
        """,
        course_id,
        status,
    )
    if row is None:
        raise ConflictError("course not found")
    return dict(row)


async def get_course_tree(conn: Conn, course_id: UUID) -> dict[str, Any] | None:
    course = await conn.fetchrow("select * from courses where id = $1", course_id)
    if course is None:
        return None

    modules = await conn.fetch(
        "select id, title, description, position from modules "
        "where course_id = $1 order by position",
        course_id,
    )
    lessons = await conn.fetch(
        """
        select l.id, l.module_id, l.title, l.slug, l.type::text as type, l.position,
               l.is_preview, l.is_required, l.duration_seconds,
               l.video_id, l.video_status::text as video_status,
               (q.id is not null) as has_quiz
        from lessons l
        join modules m on m.id = l.module_id
        left join quizzes q on q.lesson_id = l.id
        where m.course_id = $1
        order by m.position, l.position
        """,
        course_id,
    )

    by_module: dict[UUID, list[dict[str, Any]]] = {}
    for lesson in lessons:
        by_module.setdefault(lesson["module_id"], []).append(dict(lesson))

    return {
        **dict(course),
        "status": course["status"],
        "modules": [
            {**dict(module), "lessons": by_module.get(module["id"], [])}
            for module in modules
        ],
    }


async def delete_course(conn: Conn, course_id: UUID) -> None:
    enrolled = await conn.fetchval(
        "select count(*) from enrollments where course_id = $1", course_id
    )
    if enrolled:
        # Cascading would delete their progress and certificates too. Archive
        # is almost always what was meant.
        raise ConflictError(
            f"{enrolled} student(s) are enrolled; archive the course instead of deleting it"
        )
    await conn.execute("delete from courses where id = $1", course_id)


# ----------------------------------------------------- modules and lessons --

async def create_module(conn: Conn, course_id: UUID, title: str) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        insert into modules (course_id, title, position)
        values ($1, $2, coalesce((select max(position) + 1 from modules where course_id = $1), 1))
        returning id, title, position
        """,
        course_id,
        title,
    )
    return dict(row)


async def create_lesson(
    conn: Conn, module_id: UUID, *, title: str, lesson_type: str
) -> dict[str, Any]:
    slug_base = slugify(title)[:60] or "lesson"
    slug = slug_base
    suffix = 2
    while await conn.fetchval(
        "select 1 from lessons where module_id = $1 and slug = $2", module_id, slug
    ):
        slug = f"{slug_base}-{suffix}"
        suffix += 1

    row = await conn.fetchrow(
        """
        insert into lessons (module_id, title, slug, type, position)
        values ($1, $2, $3, $4::lesson_type,
                coalesce((select max(position) + 1 from lessons where module_id = $1), 1))
        returning id, title, slug, type::text as type, position, video_status::text as video_status
        """,
        module_id,
        title,
        slug,
        lesson_type,
    )
    return dict(row)


LESSON_UPDATABLE = {"title", "is_preview", "is_required", "duration_seconds", "content"}


async def update_lesson(conn: Conn, lesson_id: UUID, changes: dict[str, Any]) -> dict[str, Any]:
    fields = {k: v for k, v in changes.items() if k in LESSON_UPDATABLE}
    if "content" in fields and fields["content"] is not None:
        fields["content"] = json.dumps(fields["content"])
    if not fields:
        raise ConflictError("nothing to update")

    assignments = ", ".join(
        f"{name} = ${i + 2}" + ("::jsonb" if name == "content" else "")
        for i, name in enumerate(fields)
    )
    row = await conn.fetchrow(
        f"update lessons set {assignments} where id = $1 "
        "returning id, title, is_preview, is_required, duration_seconds",
        lesson_id,
        *fields.values(),
    )
    if row is None:
        raise ConflictError("lesson not found")
    return dict(row)


async def _reorder(
    conn: Conn, table: str, parent_column: str, parent_id: UUID, ordered_ids: list[UUID]
) -> None:
    """Rewrite positions 1..n from a full ordering.

    The caller must supply *every* child, not just the moved ones. A partial
    list would leave duplicate or missing positions, and the resulting order
    would depend on whatever the database returned first. Rejecting the request
    is better than silently producing an order nobody chose.
    """
    rows = await conn.fetch(
        f"select id from {table} where {parent_column} = $1",
        parent_id,
    )
    existing = {row["id"] for row in rows}
    if set(ordered_ids) != existing:
        raise ConflictError(
            "the ordering must list every child exactly once "
            f"({len(existing)} expected, {len(set(ordered_ids))} distinct supplied)"
        )

    await conn.executemany(
        f"update {table} set position = $1 where id = $2",
        [(index + 1, child_id) for index, child_id in enumerate(ordered_ids)],
    )


async def reorder_modules(conn: Conn, course_id: UUID, ordered_ids: list[UUID]) -> None:
    await _reorder(conn, "modules", "course_id", course_id, ordered_ids)


async def reorder_lessons(conn: Conn, module_id: UUID, ordered_ids: list[UUID]) -> None:
    await _reorder(conn, "lessons", "module_id", module_id, ordered_ids)


async def delete_module(conn: Conn, module_id: UUID) -> None:
    await conn.execute("delete from modules where id = $1", module_id)


async def delete_lesson(conn: Conn, lesson_id: UUID) -> None:
    await conn.execute("delete from lessons where id = $1", lesson_id)


# ------------------------------------------------------------------- video --

async def set_lesson_video(
    conn: Conn, lesson_id: UUID, *, video_id: str, status: str
) -> None:
    await conn.execute(
        "update lessons set video_id = $2, video_status = $3::video_status where id = $1",
        lesson_id,
        video_id,
        status,
    )


async def set_video_status(conn: Conn, lesson_id: UUID, status: str) -> None:
    await conn.execute(
        "update lessons set video_status = $2::video_status where id = $1",
        lesson_id,
        status,
    )


async def get_lesson_video(conn: Conn, lesson_id: UUID) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "select id, type::text as type, video_id, video_status::text as video_status "
        "from lessons where id = $1",
        lesson_id,
    )
    return dict(row) if row else None


# ---------------------------------------------------------------- students --

@dataclass(frozen=True, slots=True)
class StudentSummary:
    user_id: UUID
    email: str
    full_name: str | None
    enrolled_count: int
    completed_count: int


async def list_students(conn: Conn, *, limit: int, offset: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        select p.id as user_id, p.email, p.full_name, p.created_at,
               count(e.id) filter (where e.status = 'active') as enrolled_count,
               count(e.id) filter (where e.completed_at is not null) as completed_count
        from profiles p
        left join enrollments e on e.user_id = p.id
        where p.role = 'student'
        group by p.id
        order by p.created_at desc
        limit $1 offset $2
        """,
        limit,
        offset,
    )
    return [dict(row) for row in rows]


async def grant_enrollment(conn: Conn, *, user_id: UUID, course_id: UUID) -> dict[str, Any]:
    course = await conn.fetchrow(
        "select access_type::text as access_type, access_days from courses where id = $1",
        course_id,
    )
    if course is None:
        raise ConflictError("course not found")

    expires_at = None
    if course["access_type"] == "time_limited":
        expires_at = await conn.fetchval(
            "select now() + make_interval(days => $1)", course["access_days"]
        )

    row = await conn.fetchrow(
        """
        insert into enrollments (user_id, course_id, source, expires_at)
        values ($1, $2, 'manual', $3)
        on conflict (user_id, course_id) do update
          set status = 'active', expires_at = excluded.expires_at
        returning id, status::text as status, expires_at
        """,
        user_id,
        course_id,
        expires_at,
    )
    return dict(row)


async def revoke_enrollment(conn: Conn, enrollment_id: UUID) -> None:
    # Status change, not a delete: progress and any certificate stay attached,
    # so a mistaken revocation can be undone without losing the student's work.
    await conn.execute(
        "update enrollments set status = 'refunded' where id = $1", enrollment_id
    )

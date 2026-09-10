#!/usr/bin/env python3
"""Explain why a course is not at 100% for one student.

Course progress depends on a chain: a lesson has to be completable, the student
has to complete it, and the enrollment has to be recomputed. When the bar does
not move, one link is broken and the UI cannot say which. This prints every
link.

    export DATABASE_URL=<the same value as apps/api/.env>
    python3 scripts/diagnose_progress.py you@example.com pilot-course

Read-only.
"""

from __future__ import annotations

import asyncio
import os
import sys

try:
    import asyncpg
except ImportError:
    sys.exit("asyncpg is not installed. Run this from apps/api with its venv active:\n"
             "  cd apps/api && . .venv/bin/activate && python ../../scripts/diagnose_progress.py ...")

TICK, CROSS, DASH = "ok  ", "BLOCKED", "-   "


async def main(email: str, slug: str) -> int:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("set DATABASE_URL (the same value as apps/api/.env)", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        user = await conn.fetchrow(
            "select id, email, role::text as role from profiles where lower(email) = lower($1)",
            email,
        )
        if user is None:
            print(f"no account with email {email}")
            return 1

        course = await conn.fetchrow(
            "select id, title, slug, status::text as status, completion_threshold "
            "from courses where slug = $1",
            slug,
        )
        if course is None:
            print(f"no course with slug {slug}")
            return 1

        print(f"student : {user['email']}  (role {user['role']})")
        print(f"course  : {course['title']}  [{course['status']}]  "
              f"completion threshold {course['completion_threshold']}%")

        enrollment = await conn.fetchrow(
            "select id, status::text as status, progress_percent, completed_at, expires_at "
            "from enrollments where user_id = $1 and course_id = $2",
            user["id"], course["id"],
        )
        if enrollment is None:
            print("\nNOT ENROLLED — nothing can be recorded. Enroll from the course page.")
            return 1
        print(f"enrolled: {enrollment['status']}  stored progress "
              f"{enrollment['progress_percent']}%"
              + (f"  expires {enrollment['expires_at']}" if enrollment["expires_at"] else ""))

        rows = await conn.fetch(
            """
            select l.id, l.title, l.type::text as type, l.is_required,
                   l.duration_seconds, l.video_status::text as video_status, l.video_id,
                   lp.watched_seconds, lp.completed,
                   q.id as quiz_id, q.passing_score,
                   (select max(qa.score) from quiz_attempts qa
                     where qa.quiz_id = q.id and qa.user_id = $2) as best_score,
                   (select bool_or(qa.passed) from quiz_attempts qa
                     where qa.quiz_id = q.id and qa.user_id = $2) as quiz_passed,
                   a.id as assignment_id, a.is_graded,
                   (select s.status::text from assignment_submissions s
                     where s.assignment_id = a.id and s.user_id = $2
                     order by s.attempt_number desc limit 1) as submission_status,
                   (select bool_or(s.passed) from assignment_submissions s
                     where s.assignment_id = a.id and s.user_id = $2) as assignment_passed
            from lessons l
            join modules m on m.id = l.module_id
            left join lesson_progress lp on lp.lesson_id = l.id and lp.user_id = $2
            left join quizzes q on q.lesson_id = l.id
            left join assignments a on a.lesson_id = l.id
            where m.course_id = $1
            order by m.position, l.position
            """,
            course["id"], user["id"],
        )

        print(f"\n{'lesson':<26} {'type':<11} {'req':<4} {'state':<7} why")
        print("-" * 96)
        blockers: list[str] = []

        for row in rows:
            done = bool(row["completed"])
            state = TICK if done else (CROSS if row["is_required"] else DASH)
            why = ""

            if row["type"] == "video":
                if not row["video_id"]:
                    why = "no video uploaded"
                elif row["video_status"] != "ready":
                    why = f"video is {row['video_status']}"
                elif row["duration_seconds"] is None:
                    # This is the common one after uploading before durations
                    # were captured: with no length there is no 90% to reach.
                    why = ("no duration recorded -> the watch rule cannot fire. "
                           "Use 'Detect length' in the editor, or Mark as complete")
                else:
                    need = -(-row["duration_seconds"] * course["completion_threshold"] // 100)
                    got = row["watched_seconds"] or 0
                    why = f"watched {got}s of {need}s needed ({row['duration_seconds']}s long)"
            elif row["type"] == "quiz":
                if row["quiz_id"] is None:
                    why = "no quiz attached to this lesson"
                elif row["quiz_passed"]:
                    why = f"passed (best {row['best_score']}%)"
                elif row["best_score"] is not None:
                    why = (f"best {row['best_score']}% vs pass mark "
                           f"{row['passing_score']}% -> not passed")
                else:
                    why = "no attempt yet"
            elif row["type"] == "assignment":
                if row["assignment_id"] is None:
                    why = "no assignment attached to this lesson"
                elif row["assignment_passed"]:
                    why = "graded as a pass"
                elif row["submission_status"] == "submitted":
                    why = "submitted, awaiting grading"
                elif row["submission_status"] is None:
                    why = "not submitted"
                else:
                    why = f"graded but not passed ({row['submission_status']})"
            else:
                why = "mark as complete on the lesson page"

            print(f"{row['title'][:25]:<26} {row['type']:<11} "
                  f"{'yes' if row['is_required'] else 'no':<4} {state:<7} {why}")
            if row["is_required"] and not done:
                blockers.append(f"{row['title']}: {why}")

        required = [r for r in rows if r["is_required"]]
        complete = [r for r in required if r["completed"]]

        # The bar is fractional: a part-watched video counts as the share of its
        # target actually watched, so the stored value legitimately sits above a
        # plain count of finished lessons.
        credit = 0.0
        for row in required:
            if row["completed"]:
                credit += 1.0
            elif row["type"] == "video" and row["duration_seconds"]:
                target = -(-row["duration_seconds"] * course["completion_threshold"] // 100)
                credit += min(0.99, (row["watched_seconds"] or 0) / max(target, 1))
        expected = round(credit / len(required) * 100, 2) if required else 0.0

        print("-" * 96)
        print(f"\n{len(complete)} of {len(required)} required lessons complete; "
              f"with part-watched video counted, the bar should read {expected}%")
        if abs(float(enrollment["progress_percent"]) - expected) > 0.5:
            print(f"stored progress is {enrollment['progress_percent']}%, which disagrees. "
                  "Watch or complete anything to force a recompute.")

        if blockers:
            print("\nblocking 100%:")
            for item in blockers:
                print(f"  - {item}")
        else:
            print("\nnothing blocking — this course is complete.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: diagnose_progress.py <email> <course-slug>")
    raise SystemExit(asyncio.run(main(sys.argv[1], sys.argv[2])))

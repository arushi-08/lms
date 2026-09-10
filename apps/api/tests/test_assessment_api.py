"""Quizzes and assignments end to end: authoring, submitting, grading."""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ALICE

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    from app.db import build_database
    from app.providers.video.factory import build_video_provider

    app = create_app(settings)
    database = build_database(settings)
    await database.connect()
    app.state.database = database
    app.state.video_provider = build_video_provider(settings)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            yield http
    finally:
        await database.disconnect()


@pytest.fixture
async def conn(settings: Settings) -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(settings.database_url.get_secret_value())
    try:
        yield connection
    finally:
        await connection.close()


@pytest.fixture(autouse=True)
async def cleanup(conn: asyncpg.Connection) -> AsyncIterator[None]:
    before = {r["id"] for r in await conn.fetch("select id from courses")}
    yield
    after = {r["id"] for r in await conn.fetch("select id from courses")}
    created = after - before
    if created:
        await conn.execute(
            "delete from enrollments where course_id = any($1::uuid[])", list(created)
        )
        await conn.execute("delete from courses where id = any($1::uuid[])", list(created))
    await conn.execute("delete from assignment_submissions")
    await conn.execute("delete from assignments")
    await conn.execute("delete from audit_log")


async def scaffold(client: AsyncClient, admin_auth, lesson_type: str) -> tuple[str, str]:
    """A published course with one lesson of the given type, Alice enrolled."""
    course = await client.post(
        "/api/admin/courses", headers=admin_auth, json={"title": "Assessment Course"}
    )
    course_id = course.json()["id"]
    module = await client.post(
        f"/api/admin/courses/{course_id}/modules", headers=admin_auth, json={"title": "M"}
    )
    lesson = await client.post(
        f"/api/admin/modules/{module.json()['id']}/lessons",
        headers=admin_auth,
        json={"title": "Assessment", "type": lesson_type},
    )
    await client.post(f"/api/admin/courses/{course_id}/publish", headers=admin_auth)
    await client.post(
        "/api/admin/enrollments",
        headers=admin_auth,
        json={"user_id": str(ALICE), "course_id": course_id},
    )
    return course_id, lesson.json()["id"]


class TestQuizAuthoring:
    async def test_build_a_quiz_and_take_it(self, client, admin_auth, alice_auth) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "quiz")

        quiz = await client.put(
            f"/api/admin/lessons/{lesson_id}/quiz",
            headers=admin_auth,
            json={"title": "Check", "passing_score": 50},
        )
        assert quiz.status_code == 200
        quiz_id = quiz.json()["id"]

        saved = await client.put(
            f"/api/admin/quizzes/{quiz_id}/questions",
            headers=admin_auth,
            json={
                "type": "single",
                "prompt": "Which is right?",
                "points": 1,
                "options": [
                    {"text": "Right", "is_correct": True},
                    {"text": "Wrong", "is_correct": False},
                ],
            },
        )
        assert saved.status_code == 200

        # The student's view must not carry the key.
        student = await client.get(f"/api/quizzes/{quiz_id}", headers=alice_auth)
        assert student.status_code == 200
        import json as _json

        assert "is_correct" not in _json.dumps(student.json())

        correct = next(
            o["id"]
            for q in student.json()["questions"]
            for o in q["options"]
            if o["text"] == "Right"
        )
        question_id = student.json()["questions"][0]["id"]
        attempt = await client.post(
            f"/api/quizzes/{quiz_id}/attempts",
            headers=alice_auth,
            json={"responses": [{"question_id": question_id, "selected_option_ids": [correct]}]},
        )
        assert attempt.status_code == 200
        assert attempt.json()["passed"] is True

    async def test_single_answer_question_needs_exactly_one_correct(
        self, client, admin_auth
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "quiz")
        quiz = await client.put(
            f"/api/admin/lessons/{lesson_id}/quiz",
            headers=admin_auth,
            json={"title": "Check"},
        )
        response = await client.put(
            f"/api/admin/quizzes/{quiz.json()['id']}/questions",
            headers=admin_auth,
            json={
                "type": "single",
                "prompt": "Two rights?",
                "options": [
                    {"text": "A", "is_correct": True},
                    {"text": "B", "is_correct": True},
                ],
            },
        )
        assert response.status_code == 422

    async def test_choice_question_needs_a_correct_option(self, client, admin_auth) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "quiz")
        quiz = await client.put(
            f"/api/admin/lessons/{lesson_id}/quiz", headers=admin_auth, json={"title": "Q"}
        )
        response = await client.put(
            f"/api/admin/quizzes/{quiz.json()['id']}/questions",
            headers=admin_auth,
            json={
                "type": "single",
                "prompt": "No answer marked",
                "options": [{"text": "A"}, {"text": "B"}],
            },
        )
        assert response.status_code == 422

    async def test_answered_question_cannot_be_edited(
        self, client, admin_auth, alice_auth
    ) -> None:
        # Rewriting a question students already answered would silently change
        # what their recorded responses mean.
        _, lesson_id = await scaffold(client, admin_auth, "quiz")
        quiz = await client.put(
            f"/api/admin/lessons/{lesson_id}/quiz", headers=admin_auth, json={"title": "Q"}
        )
        quiz_id = quiz.json()["id"]
        created = await client.put(
            f"/api/admin/quizzes/{quiz_id}/questions",
            headers=admin_auth,
            json={
                "type": "boolean",
                "prompt": "True?",
                "options": [{"text": "True", "is_correct": True}, {"text": "False"}],
            },
        )
        question_id = created.json()["id"]

        await client.post(
            f"/api/quizzes/{quiz_id}/attempts", headers=alice_auth, json={"responses": []}
        )

        response = await client.put(
            f"/api/admin/quizzes/{quiz_id}/questions",
            headers=admin_auth,
            json={
                "id": question_id,
                "type": "boolean",
                "prompt": "Changed",
                "options": [{"text": "True", "is_correct": True}, {"text": "False"}],
            },
        )
        assert response.status_code == 409

    async def test_students_cannot_read_the_editing_view(
        self, client, admin_auth, alice_auth
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "quiz")
        await client.put(
            f"/api/admin/lessons/{lesson_id}/quiz", headers=admin_auth, json={"title": "Q"}
        )
        response = await client.get(
            f"/api/admin/lessons/{lesson_id}/quiz", headers=alice_auth
        )
        assert response.status_code == 403


class TestAssignments:
    async def test_author_submit_and_grade(self, client, admin_auth, alice_auth) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "assignment")

        created = await client.put(
            f"/api/admin/lessons/{lesson_id}/assignment",
            headers=admin_auth,
            json={
                "title": "Reflection",
                "instructions": "Write 200 words.",
                "passing_score": 60,
            },
        )
        assert created.status_code == 200
        assignment_id = created.json()["id"]

        brief = await client.get(f"/api/lessons/{lesson_id}/assignment", headers=alice_auth)
        assert brief.status_code == 200
        assert brief.json()["instructions"] == "Write 200 words."
        assert brief.json()["submissions"] == []

        submitted = await client.post(
            f"/api/assignments/{assignment_id}/submissions",
            headers=alice_auth,
            json={"text_answer": "Here is my reflection."},
        )
        assert submitted.status_code == 201
        submission_id = submitted.json()["id"]

        queue = await client.get("/api/admin/submissions", headers=admin_auth)
        assert any(row["id"] == submission_id for row in queue.json())

        graded = await client.post(
            f"/api/admin/submissions/{submission_id}/grade",
            headers=admin_auth,
            json={"score": 80, "feedback": "Good work."},
        )
        assert graded.status_code == 200
        assert graded.json()["passed"] is True

        after = await client.get(f"/api/lessons/{lesson_id}/assignment", headers=alice_auth)
        assert after.json()["submissions"][0]["feedback"] == "Good work."

    async def test_pass_is_derived_from_the_threshold_not_the_grader(
        self, client, admin_auth, alice_auth
    ) -> None:
        # The certificate rule reads `passed`; letting a grader set it
        # independently of the score would let the two disagree.
        _, lesson_id = await scaffold(client, admin_auth, "assignment")
        created = await client.put(
            f"/api/admin/lessons/{lesson_id}/assignment",
            headers=admin_auth,
            json={"title": "A", "instructions": "x", "passing_score": 70},
        )
        submitted = await client.post(
            f"/api/assignments/{created.json()['id']}/submissions",
            headers=alice_auth,
            json={"text_answer": "attempt"},
        )
        graded = await client.post(
            f"/api/admin/submissions/{submitted.json()['id']}/grade",
            headers=admin_auth,
            json={"score": 69},
        )
        assert graded.json()["passed"] is False

    async def test_empty_submission_is_rejected(self, client, admin_auth, alice_auth) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "assignment")
        created = await client.put(
            f"/api/admin/lessons/{lesson_id}/assignment",
            headers=admin_auth,
            json={"title": "A", "instructions": "x"},
        )
        response = await client.post(
            f"/api/assignments/{created.json()['id']}/submissions",
            headers=alice_auth,
            json={"text_answer": "   "},
        )
        assert response.status_code == 422

    async def test_link_refused_when_the_assignment_does_not_accept_one(
        self, client, admin_auth, alice_auth
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "assignment")
        created = await client.put(
            f"/api/admin/lessons/{lesson_id}/assignment",
            headers=admin_auth,
            json={"title": "A", "instructions": "x", "allow_link": False},
        )
        response = await client.post(
            f"/api/assignments/{created.json()['id']}/submissions",
            headers=alice_auth,
            json={"link_url": "https://example.com/work"},
        )
        assert response.status_code == 400

    async def test_resubmission_keeps_the_earlier_attempt(
        self, client, admin_auth, alice_auth
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "assignment")
        created = await client.put(
            f"/api/admin/lessons/{lesson_id}/assignment",
            headers=admin_auth,
            json={"title": "A", "instructions": "x"},
        )
        assignment_id = created.json()["id"]
        for text in ("first", "second"):
            await client.post(
                f"/api/assignments/{assignment_id}/submissions",
                headers=alice_auth,
                json={"text_answer": text},
            )
        brief = await client.get(f"/api/lessons/{lesson_id}/assignment", headers=alice_auth)
        attempts = [s["attempt_number"] for s in brief.json()["submissions"]]
        assert attempts == [2, 1]

    async def test_students_cannot_reach_the_grading_queue(self, client, alice_auth) -> None:
        assert (
            await client.get("/api/admin/submissions", headers=alice_auth)
        ).status_code == 403

    async def test_students_cannot_grade(self, client, admin_auth, alice_auth) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "assignment")
        created = await client.put(
            f"/api/admin/lessons/{lesson_id}/assignment",
            headers=admin_auth,
            json={"title": "A", "instructions": "x"},
        )
        submitted = await client.post(
            f"/api/assignments/{created.json()['id']}/submissions",
            headers=alice_auth,
            json={"text_answer": "mine"},
        )
        response = await client.post(
            f"/api/admin/submissions/{submitted.json()['id']}/grade",
            headers=alice_auth,
            json={"score": 100},
        )
        assert response.status_code == 403

    async def test_non_enrolled_student_cannot_read_or_submit(
        self, client, admin_auth, bob_auth
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "assignment")
        created = await client.put(
            f"/api/admin/lessons/{lesson_id}/assignment",
            headers=admin_auth,
            json={"title": "A", "instructions": "x"},
        )
        assert (
            await client.get(f"/api/lessons/{lesson_id}/assignment", headers=bob_auth)
        ).status_code == 403
        assert (
            await client.post(
                f"/api/assignments/{created.json()['id']}/submissions",
                headers=bob_auth,
                json={"text_answer": "not mine"},
            )
        ).status_code == 403


class TestCourseProgressMoves:
    """The bar was stuck at 0% because nothing could ever complete a lesson."""

    async def test_passing_a_quiz_completes_its_lesson(
        self, client, admin_auth, alice_auth, conn
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "quiz")
        quiz = await client.put(
            f"/api/admin/lessons/{lesson_id}/quiz",
            headers=admin_auth,
            json={"title": "Q", "passing_score": 50},
        )
        await client.put(
            f"/api/admin/quizzes/{quiz.json()['id']}/questions",
            headers=admin_auth,
            json={
                "type": "boolean",
                "prompt": "True?",
                "options": [{"text": "True", "is_correct": True}, {"text": "False"}],
            },
        )
        student = await client.get(f"/api/quizzes/by-lesson/{lesson_id}", headers=alice_auth)
        question = student.json()["questions"][0]
        correct = next(o["id"] for o in question["options"] if o["text"] == "True")

        result = await client.post(
            f"/api/quizzes/{student.json()['quiz_id']}/attempts",
            headers=alice_auth,
            json={"responses": [{"question_id": question["id"], "selected_option_ids": [correct]}]},
        )
        assert result.json()["passed"] is True
        # One required lesson in the course, now complete.
        assert result.json()["course_progress_percent"] == 100.0
        assert await conn.fetchval(
            "select completed from lesson_progress where lesson_id = $1", lesson_id
        )

    async def test_failing_a_quiz_does_not_complete_it(
        self, client, admin_auth, alice_auth, conn
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "quiz")
        quiz = await client.put(
            f"/api/admin/lessons/{lesson_id}/quiz",
            headers=admin_auth,
            json={"title": "Q", "passing_score": 50},
        )
        await client.put(
            f"/api/admin/quizzes/{quiz.json()['id']}/questions",
            headers=admin_auth,
            json={
                "type": "boolean",
                "prompt": "True?",
                "options": [{"text": "True", "is_correct": True}, {"text": "False"}],
            },
        )
        student = await client.get(f"/api/quizzes/by-lesson/{lesson_id}", headers=alice_auth)
        result = await client.post(
            f"/api/quizzes/{student.json()['quiz_id']}/attempts",
            headers=alice_auth,
            json={"responses": []},
        )
        assert result.json()["passed"] is False
        assert result.json()["course_progress_percent"] == 0.0
        assert not await conn.fetchval(
            "select coalesce(completed, false) from lesson_progress where lesson_id = $1",
            lesson_id,
        )

    async def test_text_lesson_can_be_marked_complete(
        self, client, admin_auth, alice_auth
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "text")
        response = await client.post(
            f"/api/lessons/{lesson_id}/complete", headers=alice_auth
        )
        assert response.status_code == 200
        assert response.json()["completed"] is True
        assert response.json()["course_progress_percent"] == 100.0

    async def test_video_of_unknown_length_can_be_marked_complete(
        self, client, admin_auth, alice_auth
    ) -> None:
        # Otherwise a lesson whose duration was never recorded is stuck forever.
        _, lesson_id = await scaffold(client, admin_auth, "video")
        response = await client.post(
            f"/api/lessons/{lesson_id}/complete", headers=alice_auth
        )
        assert response.status_code == 200

    async def test_video_of_known_length_must_be_watched(
        self, client, admin_auth, alice_auth, conn
    ) -> None:
        # Once the platform knows how long it is, clicking past it is refused.
        _, lesson_id = await scaffold(client, admin_auth, "video")
        await conn.execute(
            "update lessons set duration_seconds = 600 where id = $1", lesson_id
        )
        response = await client.post(
            f"/api/lessons/{lesson_id}/complete", headers=alice_auth
        )
        assert response.status_code == 400
        assert "watch" in response.json()["detail"]

    async def test_quiz_lesson_cannot_be_clicked_complete(
        self, client, admin_auth, alice_auth
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "quiz")
        response = await client.post(
            f"/api/lessons/{lesson_id}/complete", headers=alice_auth
        )
        assert response.status_code == 400

    async def test_passing_grade_completes_the_assignment_lesson(
        self, client, admin_auth, alice_auth, conn
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "assignment")
        created = await client.put(
            f"/api/admin/lessons/{lesson_id}/assignment",
            headers=admin_auth,
            json={"title": "A", "instructions": "x", "passing_score": 60},
        )
        submitted = await client.post(
            f"/api/assignments/{created.json()['id']}/submissions",
            headers=alice_auth,
            json={"text_answer": "my work"},
        )
        assert not await conn.fetchval(
            "select coalesce(completed, false) from lesson_progress where lesson_id = $1",
            lesson_id,
        )

        await client.post(
            f"/api/admin/submissions/{submitted.json()['id']}/grade",
            headers=admin_auth,
            json={"score": 90},
        )
        assert await conn.fetchval(
            "select completed from lesson_progress where lesson_id = $1", lesson_id
        )

    async def test_ungraded_assignment_completes_on_submission(
        self, client, admin_auth, alice_auth, conn
    ) -> None:
        # No grade is coming, so waiting for one would strand the lesson.
        _, lesson_id = await scaffold(client, admin_auth, "assignment")
        created = await client.put(
            f"/api/admin/lessons/{lesson_id}/assignment",
            headers=admin_auth,
            json={"title": "A", "instructions": "x", "is_graded": False},
        )
        await client.post(
            f"/api/assignments/{created.json()['id']}/submissions",
            headers=alice_auth,
            json={"text_answer": "handed in"},
        )
        assert await conn.fetchval(
            "select completed from lesson_progress where lesson_id = $1", lesson_id
        )

    async def test_non_enrolled_student_cannot_mark_complete(
        self, client, admin_auth, bob_auth
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "text")
        response = await client.post(f"/api/lessons/{lesson_id}/complete", headers=bob_auth)
        assert response.status_code == 403

    async def test_playback_grant_reports_progress_so_far(
        self, client, admin_auth, alice_auth, conn
    ) -> None:
        """The player continues the total instead of starting over.

        currentTime is a position, not accumulated watch time. A player that
        reported it directly would, on a re-watch, send numbers below what the
        server already credited — and since credit only counts increases, the
        lesson could never be finished by anyone who left and came back.
        """
        _, lesson_id = await scaffold(client, admin_auth, "video")
        await conn.execute(
            "update lessons set duration_seconds = 600, video_id = 'v', "
            "video_status = 'ready' where id = $1",
            lesson_id,
        )
        await client.post(
            f"/api/lessons/{lesson_id}/progress",
            headers=alice_auth,
            json={"watched_seconds": 45, "position_seconds": 45},
        )

        grant = await client.post(f"/api/lessons/{lesson_id}/playback", headers=alice_auth)
        assert grant.status_code == 200
        assert grant.json()["watched_seconds"] == 45
        assert grant.json()["last_position_seconds"] == 45

    async def test_a_smaller_report_never_reduces_credit(
        self, client, admin_auth, alice_auth
    ) -> None:
        _, lesson_id = await scaffold(client, admin_auth, "video")
        await client.post(
            f"/api/lessons/{lesson_id}/progress",
            headers=alice_auth,
            json={"watched_seconds": 40, "position_seconds": 40},
        )
        response = await client.post(
            f"/api/lessons/{lesson_id}/progress",
            headers=alice_auth,
            json={"watched_seconds": 5, "position_seconds": 5},
        )
        assert response.json()["watched_seconds"] == 40
        assert response.json()["last_position_seconds"] == 5

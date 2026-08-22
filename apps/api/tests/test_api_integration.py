"""End-to-end API tests against a real database with the real migrations.

The emphasis is on the boundaries a paying student would probe: watching
something they have not bought, keeping access after it expires, reading the
answer key out of a quiz payload, and claiming a lesson watched without
watching it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ALICE, token_for

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        # Drive the lifespan by hand so the pool exists without a live server.
        from app.db import build_database
        from app.providers.video.factory import build_video_provider

        database = build_database(settings)
        await database.connect()
        app.state.database = database
        app.state.video_provider = build_video_provider(settings)
        try:
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


async def lesson_id(conn: asyncpg.Connection, slug: str) -> UUID:
    value = await conn.fetchval("select id from lessons where slug = $1", slug)
    assert value is not None, f"no lesson seeded with slug {slug}"
    return value  # type: ignore[no-any-return]


@pytest.fixture(autouse=True)
async def reset_state(conn: asyncpg.Connection) -> AsyncIterator[None]:
    """Each test starts from the same enrolment and playback state."""
    yield
    await conn.execute("delete from video_playback_sessions")
    await conn.execute("delete from quiz_responses")
    await conn.execute("delete from quiz_attempts")
    await conn.execute("delete from lesson_progress")
    await conn.execute(
        "update enrollments set status = 'active', expires_at = null, "
        "progress_percent = 0, completed_at = null"
    )


class TestAuthentication:
    async def test_missing_token_is_rejected(self, client: AsyncClient, conn) -> None:
        target = await lesson_id(conn, "going-deeper")
        response = await client.post(f"/api/lessons/{target}/playback")
        assert response.status_code == 401

    async def test_expired_token_is_rejected(self, client: AsyncClient, conn) -> None:
        target = await lesson_id(conn, "going-deeper")
        expired = token_for(ALICE, "alice@example.test", expired=True)
        response = await client.post(
            f"/api/lessons/{target}/playback", headers={"Authorization": f"Bearer {expired}"}
        )
        assert response.status_code == 401

    async def test_token_signed_with_the_wrong_key_is_rejected(
        self, client: AsyncClient, conn
    ) -> None:
        import jwt as pyjwt

        forged = pyjwt.encode(
            {"sub": str(ALICE), "aud": "authenticated", "exp": 9_999_999_999},
            "a-different-secret-also-at-least-32-bytes-long",
            algorithm="HS256",
        )
        target = await lesson_id(conn, "going-deeper")
        response = await client.post(
            f"/api/lessons/{target}/playback", headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == 401


class TestPlaybackEntitlement:
    async def test_enrolled_student_gets_a_grant(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        target = await lesson_id(conn, "going-deeper")
        response = await client.post(f"/api/lessons/{target}/playback", headers=alice_auth)
        assert response.status_code == 200

        body = response.json()
        assert body["otp"]
        assert body["playback_info"]
        # The grant is recorded, so a watermarked leak is traceable.
        recorded = await conn.fetchval(
            "select count(*) from video_playback_sessions where user_id = $1", ALICE
        )
        assert recorded == 1

    async def test_non_enrolled_student_is_refused(
        self, client: AsyncClient, conn, bob_auth
    ) -> None:
        target = await lesson_id(conn, "going-deeper")
        response = await client.post(f"/api/lessons/{target}/playback", headers=bob_auth)
        assert response.status_code == 403
        assert response.json()["detail"] == "not enrolled"

    async def test_free_preview_is_open_to_anyone_signed_in(
        self, client: AsyncClient, conn, bob_auth
    ) -> None:
        target = await lesson_id(conn, "welcome")  # is_preview = true
        response = await client.post(f"/api/lessons/{target}/playback", headers=bob_auth)
        assert response.status_code == 200

    async def test_expired_enrolment_loses_playback(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        await conn.execute("update enrollments set expires_at = now() - interval '1 day'")
        target = await lesson_id(conn, "going-deeper")
        response = await client.post(f"/api/lessons/{target}/playback", headers=alice_auth)
        assert response.status_code == 403
        assert response.json()["detail"] == "access expired"

    async def test_refunded_enrolment_loses_playback(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        # Decision 4: a refund revokes access.
        await conn.execute("update enrollments set status = 'refunded'")
        target = await lesson_id(conn, "going-deeper")
        response = await client.post(f"/api/lessons/{target}/playback", headers=alice_auth)
        assert response.status_code == 403

    async def test_draft_course_is_invisible_not_forbidden(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        # 404 rather than 403, so unpublished content cannot be discovered by
        # probing lesson ids.
        target = await lesson_id(conn, "hidden")
        response = await client.post(f"/api/lessons/{target}/playback", headers=alice_auth)
        assert response.status_code == 404

    async def test_admin_can_preview_a_draft(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        target = await lesson_id(conn, "hidden")
        response = await client.post(f"/api/lessons/{target}/playback", headers=admin_auth)
        assert response.status_code == 200

    async def test_unprocessed_video_reports_conflict(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        target = await lesson_id(conn, "going-deeper")
        await conn.execute(
            "update lessons set video_status = 'processing' where id = $1", target
        )
        try:
            response = await client.post(f"/api/lessons/{target}/playback", headers=alice_auth)
            assert response.status_code == 409
        finally:
            await conn.execute(
                "update lessons set video_status = 'ready' where id = $1", target
            )

    async def test_concurrent_session_cap_is_enforced(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        # Two grants allowed (the configured cap), the third refused -- one
        # shared login should not serve a whole class.
        target = await lesson_id(conn, "going-deeper")
        first = await client.post(f"/api/lessons/{target}/playback", headers=alice_auth)
        second = await client.post(f"/api/lessons/{target}/playback", headers=alice_auth)
        third = await client.post(f"/api/lessons/{target}/playback", headers=alice_auth)
        assert (first.status_code, second.status_code) == (200, 200)
        assert third.status_code == 429


class TestProgress:
    async def test_heartbeat_is_clamped(self, client: AsyncClient, conn, alice_auth) -> None:
        target = await lesson_id(conn, "going-deeper")
        response = await client.post(
            f"/api/lessons/{target}/progress",
            headers=alice_auth,
            json={"watched_seconds": 86_400, "position_seconds": 600},
        )
        assert response.status_code == 200
        body = response.json()
        # 600s lesson, first beat: capped at the opening allowance, nowhere near
        # the 540s needed to complete.
        assert body["watched_seconds"] == 60
        assert body["completed"] is False

    async def test_absurd_values_are_rejected_at_the_edge(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        target = await lesson_id(conn, "going-deeper")
        response = await client.post(
            f"/api/lessons/{target}/progress",
            headers=alice_auth,
            json={"watched_seconds": 10**9, "position_seconds": 0},
        )
        assert response.status_code == 422

    async def test_non_enrolled_student_cannot_record_progress(
        self, client: AsyncClient, conn, bob_auth
    ) -> None:
        target = await lesson_id(conn, "welcome")  # a preview lesson
        response = await client.post(
            f"/api/lessons/{target}/progress",
            headers=bob_auth,
            json={"watched_seconds": 10, "position_seconds": 10},
        )
        # Preview lessons are watchable without enrolling, but progress hangs
        # off an enrolment, so there is nothing to record against.
        assert response.status_code == 403

    async def test_course_percentage_tracks_completed_lessons(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        target = await lesson_id(conn, "going-deeper")
        await conn.execute(
            """
            insert into lesson_progress (user_id, lesson_id, enrollment_id, watched_seconds,
                                         completed, completed_at)
            select $1, $2, e.id, 600, true, now() from enrollments e where e.user_id = $1
            """,
            ALICE,
            target,
        )
        other = await lesson_id(conn, "worked-example")
        response = await client.post(
            f"/api/lessons/{other}/progress",
            headers=alice_auth,
            json={"watched_seconds": 30, "position_seconds": 30},
        )
        body = response.json()
        # Six required lessons in the seed, one of them complete.
        assert body["course_progress_percent"] == pytest.approx(16.67, abs=0.01)
        assert body["course_completed"] is False


class TestQuizzes:
    async def test_question_payload_contains_no_answer_key(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        quiz = await conn.fetchval("select id from quizzes limit 1")
        response = await client.get(f"/api/quizzes/{quiz}", headers=alice_auth)
        assert response.status_code == 200

        raw = json.dumps(response.json())
        # Nothing anywhere in the serialised payload may hint at correctness.
        assert "is_correct" not in raw
        assert "correct_answers" not in raw

        for question in response.json()["questions"]:
            for option in question["options"]:
                assert set(option) == {"id", "text"}

    async def test_non_enrolled_student_cannot_read_a_quiz(
        self, client: AsyncClient, conn, bob_auth
    ) -> None:
        quiz = await conn.fetchval("select id from quizzes limit 1")
        response = await client.get(f"/api/quizzes/{quiz}", headers=bob_auth)
        assert response.status_code == 403

    async def test_submission_is_graded_and_recorded(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        quiz = await conn.fetchval("select id from quizzes limit 1")
        correct = await conn.fetch(
            """
            select qq.id as question_id, qq.type::text as type,
                   coalesce(array_agg(qo.id) filter (where qo.is_correct), '{}') as options,
                   qq.correct_answers
            from quiz_questions qq
            left join quiz_options qo on qo.question_id = qq.id
            where qq.quiz_id = $1 group by qq.id
            """,
            quiz,
        )
        payload = {
            "responses": [
                {
                    "question_id": str(row["question_id"]),
                    "selected_option_ids": [str(o) for o in row["options"]],
                    "text_answer": (row["correct_answers"] or [None])[0],
                }
                for row in correct
            ]
        }
        response = await client.post(
            f"/api/quizzes/{quiz}/attempts", headers=alice_auth, json=payload
        )
        assert response.status_code == 200

        body = response.json()
        assert body["score"] == 100.0
        assert body["passed"] is True

        stored = await conn.fetchrow(
            "select score, passed, attempt_number from quiz_attempts where user_id = $1", ALICE
        )
        assert stored["passed"] is True
        assert stored["attempt_number"] == 1

    async def test_result_does_not_reveal_the_right_answers(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        # Retries are unlimited, so leaking the key in the result would let a
        # student walk to a perfect score one submission at a time.
        quiz = await conn.fetchval("select id from quizzes limit 1")
        response = await client.post(
            f"/api/quizzes/{quiz}/attempts", headers=alice_auth, json={"responses": []}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["score"] == 0.0
        assert body["passed"] is False

        raw = json.dumps(body)
        assert "correct_option" not in raw
        assert "correct_answers" not in raw
        for result in body["results"]:
            assert set(result) == {"question_id", "is_correct", "points_awarded"}

    async def test_invented_question_ids_do_not_earn_points(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        quiz = await conn.fetchval("select id from quizzes limit 1")
        response = await client.post(
            f"/api/quizzes/{quiz}/attempts",
            headers=alice_auth,
            json={
                "responses": [
                    {
                        "question_id": "99999999-9999-9999-9999-999999999999",
                        "selected_option_ids": [],
                        "text_answer": "anything",
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["score"] == 0.0
        assert response.json()["points_possible"] == 4

    async def test_attempt_cap_is_enforced_when_set(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        quiz = await conn.fetchval("select id from quizzes limit 1")
        await conn.execute("update quizzes set max_attempts = 1 where id = $1", quiz)
        try:
            first = await client.post(
                f"/api/quizzes/{quiz}/attempts", headers=alice_auth, json={"responses": []}
            )
            second = await client.post(
                f"/api/quizzes/{quiz}/attempts", headers=alice_auth, json={"responses": []}
            )
            assert first.status_code == 200
            assert second.status_code == 409
        finally:
            await conn.execute("update quizzes set max_attempts = null where id = $1", quiz)

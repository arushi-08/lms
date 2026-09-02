"""Admin API: authorisation first, then the authoring rules."""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ADMIN, ALICE

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
    """Remove anything the test created, leaving the seeded fixtures alone."""
    before = {row["id"] for row in await conn.fetch("select id from courses")}
    yield
    after = {row["id"] for row in await conn.fetch("select id from courses")}
    created = after - before
    if created:
        await conn.execute(
            "delete from enrollments where course_id = any($1::uuid[])", list(created)
        )
        await conn.execute("delete from courses where id = any($1::uuid[])", list(created))
    await conn.execute("delete from audit_log")


async def new_course(client: AsyncClient, admin_auth: dict[str, str], title="Test Course") -> str:
    response = await client.post("/api/admin/courses", headers=admin_auth, json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestAuthorisation:
    async def test_unauthenticated_is_rejected(self, client: AsyncClient) -> None:
        assert (await client.get("/api/admin/courses")).status_code == 401

    async def test_student_cannot_list_courses(self, client: AsyncClient, alice_auth) -> None:
        assert (await client.get("/api/admin/courses", headers=alice_auth)).status_code == 403

    async def test_student_cannot_create_a_course(self, client: AsyncClient, alice_auth) -> None:
        response = await client.post(
            "/api/admin/courses", headers=alice_auth, json={"title": "Mine now"}
        )
        assert response.status_code == 403

    async def test_student_claiming_admin_in_the_token_is_still_refused(
        self, client: AsyncClient, conn
    ) -> None:
        # require_admin re-reads profiles.role, so a token claim on its own
        # buys nothing. This is the check that makes revocation immediate.
        from tests.conftest import token_for

        forged_claim = token_for(ALICE, "alice@example.test", role="admin")
        response = await client.get(
            "/api/admin/courses", headers={"Authorization": f"Bearer {forged_claim}"}
        )
        assert response.status_code == 403

    async def test_admin_is_allowed(self, client: AsyncClient, admin_auth) -> None:
        assert (await client.get("/api/admin/courses", headers=admin_auth)).status_code == 200


class TestCourseLifecycle:
    async def test_new_course_starts_as_a_draft(self, client, admin_auth, conn) -> None:
        course_id = await new_course(client, admin_auth)
        status_value = await conn.fetchval(
            "select status::text from courses where id = $1", course_id
        )
        assert status_value == "draft"

    async def test_slug_collisions_get_a_suffix(self, client, admin_auth, conn) -> None:
        first = await new_course(client, admin_auth, "Same Name")
        second = await new_course(client, admin_auth, "Same Name")
        slugs = [
            await conn.fetchval("select slug from courses where id = $1", cid)
            for cid in (first, second)
        ]
        assert slugs[0] != slugs[1]
        assert slugs[1].startswith(slugs[0])

    async def test_empty_course_cannot_be_published(self, client, admin_auth) -> None:
        # An empty course in the catalog is worse than no course.
        course_id = await new_course(client, admin_auth)
        response = await client.post(f"/api/admin/courses/{course_id}/publish", headers=admin_auth)
        assert response.status_code == 409
        assert "at least one lesson" in response.json()["detail"]

    async def test_course_with_a_lesson_publishes(self, client, admin_auth, conn) -> None:
        course_id = await new_course(client, admin_auth)
        module = await client.post(
            f"/api/admin/courses/{course_id}/modules", headers=admin_auth,
            json={"title": "Module one"},
        )
        module_id = module.json()["id"]
        await client.post(
            f"/api/admin/modules/{module_id}/lessons", headers=admin_auth,
            json={"title": "Lesson one", "type": "video"},
        )

        response = await client.post(
            f"/api/admin/courses/{course_id}/publish", headers=admin_auth
        )
        assert response.status_code == 200
        assert response.json()["status"] == "published"
        assert await conn.fetchval(
            "select published_at is not null from courses where id = $1", course_id
        )

    async def test_patch_cannot_publish_a_course(self, client, admin_auth, conn) -> None:
        # status is not in the updatable allowlist, so a crafted PATCH that
        # sneaks it in must be ignored rather than applied.
        course_id = await new_course(client, admin_auth)
        response = await client.patch(
            f"/api/admin/courses/{course_id}",
            headers=admin_auth,
            json={"title": "Renamed", "status": "published", "published_at": "2020-01-01"},
        )
        assert response.status_code == 200
        assert await conn.fetchval(
            "select status::text from courses where id = $1", course_id
        ) == "draft"

    async def test_course_with_students_cannot_be_deleted(
        self, client, admin_auth, conn
    ) -> None:
        course_id = await new_course(client, admin_auth)
        await conn.execute(
            "insert into enrollments (user_id, course_id, source) values ($1, $2, 'manual')",
            ALICE, course_id,
        )
        response = await client.delete(f"/api/admin/courses/{course_id}", headers=admin_auth)
        assert response.status_code == 409
        assert "enrolled" in response.json()["detail"]

    async def test_empty_course_can_be_deleted(self, client, admin_auth) -> None:
        course_id = await new_course(client, admin_auth)
        assert (
            await client.delete(f"/api/admin/courses/{course_id}", headers=admin_auth)
        ).status_code == 204


class TestOrdering:
    async def test_full_reorder_rewrites_positions(self, client, admin_auth, conn) -> None:
        course_id = await new_course(client, admin_auth)
        ids = []
        for title in ("A", "B", "C"):
            response = await client.post(
                f"/api/admin/courses/{course_id}/modules", headers=admin_auth,
                json={"title": title},
            )
            ids.append(response.json()["id"])

        reversed_ids = list(reversed(ids))
        response = await client.post(
            f"/api/admin/courses/{course_id}/modules/reorder",
            headers=admin_auth,
            json={"ids": reversed_ids},
        )
        assert response.status_code == 200

        rows = await conn.fetch(
            "select id, position from modules where course_id = $1 order by position", course_id
        )
        assert [str(r["id"]) for r in rows] == reversed_ids
        assert [r["position"] for r in rows] == [1, 2, 3]

    async def test_partial_ordering_is_refused(self, client, admin_auth, conn) -> None:
        # Applying a partial list would leave duplicate or missing positions and
        # an order nobody chose.
        course_id = await new_course(client, admin_auth)
        ids = []
        for title in ("A", "B", "C"):
            response = await client.post(
                f"/api/admin/courses/{course_id}/modules", headers=admin_auth,
                json={"title": title},
            )
            ids.append(response.json()["id"])

        response = await client.post(
            f"/api/admin/courses/{course_id}/modules/reorder",
            headers=admin_auth,
            json={"ids": ids[:2]},
        )
        assert response.status_code == 409

        positions = [
            r["position"]
            for r in await conn.fetch(
                "select position from modules where course_id = $1 order by position", course_id
            )
        ]
        assert positions == [1, 2, 3]  # untouched

    async def test_ordering_with_a_foreign_id_is_refused(self, client, admin_auth) -> None:
        course_id = await new_course(client, admin_auth)
        response = await client.post(
            f"/api/admin/courses/{course_id}/modules", headers=admin_auth, json={"title": "A"}
        )
        mine = response.json()["id"]
        response = await client.post(
            f"/api/admin/courses/{course_id}/modules/reorder",
            headers=admin_auth,
            json={"ids": [mine, "99999999-9999-9999-9999-999999999999"]},
        )
        assert response.status_code == 409


class TestVideoUpload:
    async def test_upload_ticket_marks_the_lesson_uploading(
        self, client, admin_auth, conn
    ) -> None:
        course_id = await new_course(client, admin_auth)
        module = await client.post(
            f"/api/admin/courses/{course_id}/modules", headers=admin_auth, json={"title": "M"}
        )
        lesson = await client.post(
            f"/api/admin/modules/{module.json()['id']}/lessons",
            headers=admin_auth,
            json={"title": "Clip", "type": "video"},
        )
        lesson_id = lesson.json()["id"]

        response = await client.post(
            f"/api/admin/lessons/{lesson_id}/video/upload", headers=admin_auth
        )
        assert response.status_code == 200
        assert response.json()["upload_url"]

        row = await conn.fetchrow(
            "select video_id, video_status::text as s from lessons where id = $1", lesson_id
        )
        assert row["video_id"]
        assert row["s"] == "uploading"

    async def test_status_poll_reports_processing_then_records_it(
        self, client, admin_auth, conn
    ) -> None:
        course_id = await new_course(client, admin_auth)
        module = await client.post(
            f"/api/admin/courses/{course_id}/modules", headers=admin_auth, json={"title": "M"}
        )
        lesson = await client.post(
            f"/api/admin/modules/{module.json()['id']}/lessons",
            headers=admin_auth,
            json={"title": "Clip", "type": "video"},
        )
        lesson_id = lesson.json()["id"]
        await client.post(f"/api/admin/lessons/{lesson_id}/video/upload", headers=admin_auth)

        response = await client.get(
            f"/api/admin/lessons/{lesson_id}/video/status", headers=admin_auth
        )
        assert response.status_code == 200
        # The mock fakes encoding latency so this state is exercised before the
        # real provider account exists.
        assert response.json()["video_status"] == "processing"
        assert await conn.fetchval(
            "select video_status::text from lessons where id = $1", lesson_id
        ) == "processing"

    async def test_upload_url_is_absolute(self, client, admin_auth) -> None:
        """The browser must not resolve it against the frontend origin.

        The mock provider names its endpoint with a site-relative path, since it
        cannot know this service's public URL. Returned as-is, the browser would
        POST the file to the Next server instead of the API, and the upload
        would 404 with nothing obviously wrong in either log.
        """
        course_id = await new_course(client, admin_auth)
        module = await client.post(
            f"/api/admin/courses/{course_id}/modules", headers=admin_auth, json={"title": "M"}
        )
        lesson = await client.post(
            f"/api/admin/modules/{module.json()['id']}/lessons",
            headers=admin_auth,
            json={"title": "Clip", "type": "video"},
        )
        response = await client.post(
            f"/api/admin/lessons/{lesson.json()['id']}/video/upload", headers=admin_auth
        )
        url = response.json()["upload_url"]
        assert url.startswith("http://") or url.startswith("https://"), url
        assert url.endswith("/api/dev/video-upload")

    async def test_upload_refused_for_a_text_lesson(self, client, admin_auth) -> None:
        course_id = await new_course(client, admin_auth)
        module = await client.post(
            f"/api/admin/courses/{course_id}/modules", headers=admin_auth, json={"title": "M"}
        )
        lesson = await client.post(
            f"/api/admin/modules/{module.json()['id']}/lessons",
            headers=admin_auth,
            json={"title": "Reading", "type": "text"},
        )
        response = await client.post(
            f"/api/admin/lessons/{lesson.json()['id']}/video/upload", headers=admin_auth
        )
        assert response.status_code == 400


class TestEnrolment:
    async def test_grant_then_revoke(self, client, admin_auth, conn) -> None:
        course_id = await new_course(client, admin_auth)
        response = await client.post(
            "/api/admin/enrollments",
            headers=admin_auth,
            json={"user_id": str(ALICE), "course_id": course_id},
        )
        assert response.status_code == 201
        enrollment_id = response.json()["id"]

        assert (
            await client.delete(f"/api/admin/enrollments/{enrollment_id}", headers=admin_auth)
        ).status_code == 204

        # Revoked, not deleted: progress and certificates survive an undo.
        assert await conn.fetchval(
            "select status::text from enrollments where id = $1", enrollment_id
        ) == "refunded"

    async def test_students_list_excludes_admins(self, client, admin_auth) -> None:
        response = await client.get("/api/admin/students", headers=admin_auth)
        assert response.status_code == 200
        assert str(ADMIN) not in {row["user_id"] for row in response.json()}


class TestAudit:
    async def test_mutations_are_recorded(self, client, admin_auth, conn) -> None:
        course_id = await new_course(client, admin_auth)
        await client.patch(
            f"/api/admin/courses/{course_id}", headers=admin_auth, json={"title": "Renamed"}
        )
        actions = [
            r["action"]
            for r in await conn.fetch(
                "select action from audit_log where entity_id = $1 order by created_at",
                str(course_id),
            )
        ]
        assert actions == ["course.create", "course.update"]

    async def test_audit_records_who_did_it(self, client, admin_auth, conn) -> None:
        await new_course(client, admin_auth)
        actor = await conn.fetchval("select actor_id from audit_log limit 1")
        assert actor == ADMIN

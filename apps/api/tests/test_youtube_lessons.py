"""YouTube-hosted lessons, end to end.

The point of these is the boundary between "presented by this platform" and
"protected by it". A YouTube lesson is public wherever it is embedded, so
playback deliberately mints no OTP, records no session and applies no
concurrent-stream cap -- while the entitlement check stays exactly as strict as
it is for protected content. Each half is asserted here, because a change that
quietly moved either would look like a tidy-up in review.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.anyio

ID = "dQw4w9WgXcQ"
OTHER_ID = "9bZkp7q19f0"


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


@pytest.fixture
async def lesson_id(conn: asyncpg.Connection) -> AsyncIterator[UUID]:
    """A seeded video lesson, restored to managed video afterwards."""
    value = await conn.fetchval("select id from lessons where slug = 'going-deeper'")
    yield value
    await conn.execute(
        "update lessons set video_source = 'managed', video_id = 'vid-going-deeper', "
        "video_status = 'ready' where id = $1",
        value,
    )
    await conn.execute("delete from video_playback_sessions")
    await conn.execute("delete from audit_log")


async def attach(client: AsyncClient, admin_auth, lesson: UUID, url: str):
    return await client.put(
        f"/api/admin/lessons/{lesson}/youtube", headers=admin_auth, json={"url": url}
    )


class TestAttaching:
    async def test_an_admin_can_attach_a_watch_url(
        self, client: AsyncClient, conn, admin_auth, lesson_id: UUID
    ) -> None:
        response = await attach(
            client, admin_auth, lesson_id, f"https://www.youtube.com/watch?v={ID}&t=30s"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["video_id"] == ID
        assert body["video_source"] == "youtube"
        # Ready immediately: nothing uploads it, so nothing would ever move it
        # out of 'processing' and the lesson would never become playable.
        assert body["video_status"] == "ready"
        assert body["watch_url"] == f"https://www.youtube.com/watch?v={ID}"

    async def test_junk_is_refused_with_a_reason(
        self, client: AsyncClient, conn, admin_auth, lesson_id: UUID
    ) -> None:
        response = await attach(client, admin_auth, lesson_id, "https://vimeo.com/123")
        assert response.status_code == 422
        assert "YouTube" in response.json()["detail"]

        unchanged = await conn.fetchval(
            "select video_source::text from lessons where id = $1", lesson_id
        )
        assert unchanged == "managed"

    async def test_a_student_cannot_attach_one(
        self, client: AsyncClient, conn, alice_auth, lesson_id: UUID
    ) -> None:
        response = await attach(
            client, alice_auth, lesson_id, f"https://youtu.be/{ID}"
        )
        assert response.status_code == 403

    async def test_the_database_refuses_a_bad_id_even_past_the_api(
        self, client: AsyncClient, conn, lesson_id: UUID
    ) -> None:
        """The check constraint is the second line, and it is there because the
        id is interpolated into an iframe src. If a future endpoint writes
        these columns without going through the parser, this is what stops it."""
        with pytest.raises(asyncpg.IntegrityConstraintViolationError):
            await conn.execute(
                "update lessons set video_source = 'youtube', video_id = $2, "
                "video_status = 'ready' where id = $1",
                lesson_id,
                'not-an-id" onload="alert(1)',
            )

    async def test_detaching_returns_the_lesson_to_managed(
        self, client: AsyncClient, conn, admin_auth, lesson_id: UUID
    ) -> None:
        await attach(client, admin_auth, lesson_id, f"https://youtu.be/{ID}")
        response = await client.delete(
            f"/api/admin/lessons/{lesson_id}/youtube", headers=admin_auth
        )
        assert response.status_code == 200
        assert response.json()["video_source"] == "managed"
        assert response.json()["video_id"] is None

    async def test_detaching_a_lesson_with_no_youtube_video_is_a_conflict(
        self, client: AsyncClient, conn, admin_auth, lesson_id: UUID
    ) -> None:
        response = await client.delete(
            f"/api/admin/lessons/{lesson_id}/youtube", headers=admin_auth
        )
        assert response.status_code == 409


class TestPlayback:
    async def test_an_enrolled_student_gets_the_public_id_and_no_otp(
        self, client: AsyncClient, conn, admin_auth, alice_auth, lesson_id: UUID
    ) -> None:
        await attach(client, admin_auth, lesson_id, f"https://youtu.be/{ID}")

        response = await client.post(
            f"/api/lessons/{lesson_id}/playback", headers=alice_auth
        )
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "youtube"
        assert body["youtube_video_id"] == ID
        # Empty, not plausible-looking. A fake OTP in a log is worse than none.
        assert body["otp"] == ""
        assert body["playback_info"] == ""

    async def test_it_records_no_playback_session(
        self, client: AsyncClient, conn, admin_auth, alice_auth, lesson_id: UUID
    ) -> None:
        """The ledger exists to trace a watermarked leak and to spot shared
        logins. Neither is meaningful for a video anyone can open on YouTube,
        so a row here would be a record that proves nothing."""
        await attach(client, admin_auth, lesson_id, f"https://youtu.be/{ID}")
        await client.post(f"/api/lessons/{lesson_id}/playback", headers=alice_auth)

        sessions = await conn.fetchval(
            "select count(*) from video_playback_sessions where lesson_id = $1",
            lesson_id,
        )
        assert sessions == 0

    async def test_the_concurrent_cap_does_not_apply(
        self, client: AsyncClient, conn, admin_auth, alice_auth, lesson_id: UUID
    ) -> None:
        """Two grants is the cap for protected video. A cap on public video
        cannot stop anyone watching it -- it can only lock out a student who
        left a tab open."""
        await attach(client, admin_auth, lesson_id, f"https://youtu.be/{ID}")

        codes = [
            (
                await client.post(
                    f"/api/lessons/{lesson_id}/playback", headers=alice_auth
                )
            ).status_code
            for _ in range(4)
        ]
        assert codes == [200, 200, 200, 200]

    async def test_entitlement_is_still_enforced(
        self, client: AsyncClient, conn, admin_auth, bob_auth, lesson_id: UUID
    ) -> None:
        """The half that must NOT change. Hosting a lesson on YouTube says
        nothing about who may see it inside a gated course; opening one up is
        the is_preview flag, deliberately, and not a side effect of where the
        bytes live."""
        await attach(client, admin_auth, lesson_id, f"https://youtu.be/{ID}")

        response = await client.post(
            f"/api/lessons/{lesson_id}/playback", headers=bob_auth
        )
        assert response.status_code == 403

    async def test_a_preview_youtube_lesson_is_open(
        self, client: AsyncClient, conn, admin_auth, bob_auth, lesson_id: UUID
    ) -> None:
        """…and the way to make free content free is the flag that already
        exists, which this confirms still works for YouTube lessons."""
        await attach(client, admin_auth, lesson_id, f"https://youtu.be/{ID}")
        await conn.execute(
            "update lessons set is_preview = true where id = $1", lesson_id
        )
        try:
            response = await client.post(
                f"/api/lessons/{lesson_id}/playback", headers=bob_auth
            )
            assert response.status_code == 200
            assert response.json()["youtube_video_id"] == ID
        finally:
            await conn.execute(
                "update lessons set is_preview = false where id = $1", lesson_id
            )

    async def test_progress_still_tracks(
        self, client: AsyncClient, conn, admin_auth, alice_auth, lesson_id: UUID
    ) -> None:
        """The whole reason for embedding rather than linking out. If progress
        did not move, a student might as well have been sent to YouTube."""
        await attach(client, admin_auth, lesson_id, f"https://youtu.be/{ID}")

        response = await client.post(
            f"/api/lessons/{lesson_id}/progress",
            headers=alice_auth,
            json={"watched_seconds": 45, "position_seconds": 45},
        )
        assert response.status_code == 200
        assert response.json()["watched_seconds"] > 0

        await conn.execute("delete from lesson_progress")
        await conn.execute(
            "update enrollments set progress_percent = 0, completed_at = null"
        )

    async def test_switching_back_to_managed_restores_a_real_grant(
        self, client: AsyncClient, conn, admin_auth, alice_auth, lesson_id: UUID
    ) -> None:
        await attach(client, admin_auth, lesson_id, f"https://youtu.be/{OTHER_ID}")
        await client.delete(
            f"/api/admin/lessons/{lesson_id}/youtube", headers=admin_auth
        )
        await conn.execute(
            "update lessons set video_id = 'vid-going-deeper', video_status = 'ready' "
            "where id = $1",
            lesson_id,
        )

        response = await client.post(
            f"/api/lessons/{lesson_id}/playback", headers=alice_auth
        )
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "mock"
        assert body["otp"] != ""
        assert body["youtube_video_id"] is None

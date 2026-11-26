"""The mock provider's upload store: round trip, location, and failing usefully.

None of this was covered, and the gap cost a pilot its videos. The store
defaulted to the system temp directory; macOS swept it; lesson rows went on
reporting `ready` while every playback answered "no such video" — which reads
like a database problem and is not one.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app

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


class TestRoundTrip:
    async def test_an_uploaded_clip_plays_back_byte_for_byte(
        self, client: AsyncClient
    ) -> None:
        clip = b"\x00\x01fake mp4 bytes\xff" * 64

        upload = await client.post(
            "/api/dev/video-upload",
            data={"video_id": "mock-roundtrip"},
            files={"file": ("clip.mp4", clip, "video/mp4")},
        )
        assert upload.status_code == 204, upload.text

        played = await client.get("/api/dev/video/mock-roundtrip")
        assert played.status_code == 200
        assert played.content == clip

    async def test_it_lands_in_the_configured_directory(
        self, client: AsyncClient, settings: Settings
    ) -> None:
        """The setting is the point of the change, so assert it is honoured
        rather than assuming the route reads it."""
        await client.post(
            "/api/dev/video-upload",
            data={"video_id": "mock-located"},
            files={"file": ("clip.mp4", b"bytes", "video/mp4")},
        )
        assert (settings.mock_video_dir / "mock-located.bin").exists()


class TestWhereItDefaultsTo:
    def test_the_default_is_not_the_system_temp_directory(self) -> None:
        """Where this defaults to *is* the bug, so pin it.

        Not a style preference: $TMPDIR is swept by the OS after a few days and
        cleared on reboot, and a clip uploaded once and watched over the
        following weeks is exactly what this provider is for during the pilot.
        """
        default = Settings.model_fields["mock_video_dir"].default
        assert not str(default).startswith(tempfile.gettempdir())
        assert default.parts[-2:] == (".media", "video")


class TestMissingFile:
    async def test_it_says_what_to_do(self, client: AsyncClient) -> None:
        response = await client.get("/api/dev/video/mock-never-uploaded")
        assert response.status_code == 404
        detail = response.json()["detail"]
        # The old message was "no such video", which sent someone looking in
        # Supabase for a file that had never been there.
        assert "re-upload" in detail
        assert "Supabase" in detail

    async def test_a_traversing_id_is_still_refused(self, client: AsyncClient) -> None:
        """The id reaches the filesystem, and it stayed validated across the
        refactor that moved the directory behind a setting."""
        response = await client.get("/api/dev/video/..%2F..%2F..%2Fetc%2Fpasswd")
        assert response.status_code in (400, 404)
        assert "root:" not in response.text

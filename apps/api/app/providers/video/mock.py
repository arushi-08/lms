"""In-process video provider for local development, CI and the pilot.

Exists because the VdoCipher account does not yet, and a week of work should not
wait on a vendor signup. It imitates the real handshake closely enough that the
code above it -- entitlement checks, OTP issuance, the playback ledger, the
player's request cycle -- is the same code that will run in production. Only the
transport differs.

It fakes encoding latency too: a freshly created video reports ``processing``
for a short while before ``ready``, because "the upload succeeded but the video
is not playable yet" is a real state the admin UI has to handle, and it is much
cheaper to discover that now than after the account exists.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from app.providers.video.base import (
    PlaybackGrant,
    UploadTicket,
    VideoProviderError,
    Viewer,
)

#: How long a mock upload pretends to still be encoding.
FAKE_ENCODING_SECONDS = 8


class MockVideoProvider:
    name = "mock"

    def __init__(self, *, otp_ttl_seconds: int = 300, sample_url: str = "/samples/sample.mp4") -> None:
        self._ttl = otp_ttl_seconds
        self._sample_url = sample_url
        self._created_at: dict[str, datetime] = {}

    async def create_upload(self, title: str) -> UploadTicket:
        digest = hashlib.sha256(f"{title}{secrets.token_hex(8)}".encode()).hexdigest()[:20]
        video_id = f"mock-{digest}"
        self._created_at[video_id] = datetime.now(UTC)
        return UploadTicket(
            video_id=video_id,
            upload_url="/api/dev/video-upload",
            upload_fields={"video_id": video_id},
        )

    async def issue_playback(self, video_id: str, viewer: Viewer) -> PlaybackGrant:
        if not video_id:
            raise VideoProviderError("mock provider requires a video id")

        # The OTP is bound to the viewer so tests can assert that two students
        # never receive the same grant -- the real provider behaves that way and
        # code above must not accidentally rely on grants being shareable.
        seed = f"{video_id}:{viewer.user_id}:{secrets.token_hex(8)}"
        otp = hashlib.sha256(seed.encode()).hexdigest()[:32]

        return PlaybackGrant(
            video_id=video_id,
            otp=otp,
            playback_info=f"mock-playback-info:{video_id}",
            expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl),
            direct_url=self._sample_url,
        )

    async def get_status(self, video_id: str) -> str:
        created = self._created_at.get(video_id)
        if created is None:
            return "ready"
        if datetime.now(UTC) - created < timedelta(seconds=FAKE_ENCODING_SECONDS):
            return "processing"
        return "ready"

    async def delete(self, video_id: str) -> None:
        self._created_at.pop(video_id, None)


class ExplodingVideoProvider:
    """Provider that always fails. Used in tests to assert the API degrades
    gracefully rather than leaking provider detail to the client."""

    name = "exploding"

    async def create_upload(self, title: str) -> UploadTicket:
        raise VideoProviderError("upstream unavailable")

    async def issue_playback(self, video_id: str, viewer: Viewer) -> PlaybackGrant:
        raise VideoProviderError("upstream unavailable")

    async def get_status(self, video_id: str) -> str:
        raise VideoProviderError("upstream unavailable")

    async def delete(self, video_id: str) -> None:
        raise VideoProviderError("upstream unavailable")

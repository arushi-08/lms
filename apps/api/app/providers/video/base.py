"""The video provider seam.

The platform is being built before the VdoCipher account exists, so playback
sits behind this protocol with two implementations: a mock for local work and
CI, and the real one. Selecting between them is one environment variable.

What matters is that the *entitlement check happens above this seam*, in the
route, identically for both implementations. The provider's job is to mint a
grant for a viewer who has already been authorised; it is never the thing
deciding whether they may watch. That keeps the security-critical logic in one
place and testable without a vendor account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


class VideoProviderError(RuntimeError):
    """The upstream provider failed. Never carries provider credentials."""


@dataclass(frozen=True, slots=True)
class Viewer:
    """Who is watching. Burned into the watermark, so a leak has a name on it."""

    user_id: UUID
    email: str
    ip: str | None = None


@dataclass(frozen=True, slots=True)
class UploadTicket:
    """Credentials for the browser to upload directly to the provider.

    The file never passes through our backend: a 50-video course would
    otherwise mean 50 large uploads through a 512 MB Render instance.
    """

    video_id: str
    upload_url: str
    upload_fields: dict[str, str]


@dataclass(frozen=True, slots=True)
class PlaybackGrant:
    """A short-lived permission to play one video, for one viewer, once."""

    video_id: str
    otp: str
    playback_info: str
    expires_at: datetime
    #: Only set by the mock provider. In production the browser receives an OTP
    #: and the player resolves the stream itself -- no URL is ever exposed.
    direct_url: str | None = None


class VideoProvider(Protocol):
    name: str

    async def create_upload(self, title: str) -> UploadTicket: ...

    async def issue_playback(self, video_id: str, viewer: Viewer) -> PlaybackGrant: ...

    async def get_status(self, video_id: str) -> str: ...

    async def delete(self, video_id: str) -> None: ...

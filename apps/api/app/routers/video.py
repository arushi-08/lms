"""Playback grants.

This is the route the "no student downloads" requirement rests on. The sequence
is fixed and every step matters:

1. Authenticate the caller.
2. Check entitlement against the database -- enrolment active, not expired, or
   the lesson is a free preview.
3. Check the concurrent-session cap, so one shared login cannot serve a class.
4. Only then ask the provider for a short-lived, watermarked OTP.
5. Record the grant, so a watermarked leak can be traced to an account.

No stream URL is produced anywhere in this file. The browser receives an OTP
that expires in minutes and is useless to anyone else.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.providers.video.base import VideoProviderError, Viewer
from app.repositories import learning
from app.security.deps import (
    CurrentUserDep,
    DatabaseDep,
    SettingsDep,
    VideoProviderDep,
    resolve_entitlement,
)

router = APIRouter(prefix="/lessons", tags=["video"])


class PlaybackResponse(BaseModel):
    lesson_id: UUID
    otp: str
    playback_info: str
    expires_at: str
    #: Populated only by the mock provider in development.
    direct_url: str | None = None


@router.post("/{lesson_id}/playback", response_model=PlaybackResponse)
async def create_playback_grant(
    lesson_id: UUID,
    request: Request,
    user: CurrentUserDep,
    database: DatabaseDep,
    provider: VideoProviderDep,
    settings: SettingsDep,
) -> PlaybackResponse:
    async with database.acquire() as conn:
        entitlement = await resolve_entitlement(
            conn, lesson_id=lesson_id, user=user, require_enrollment=False
        )
        context = entitlement.context

        if context.lesson_type != "video":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="lesson is not a video"
            )
        if not context.video_id or context.video_status != "ready":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="video is not ready yet"
            )

        # Admins reviewing content should not be throttled by the student cap.
        if not entitlement.is_admin:
            live = await learning.count_live_playback_sessions(conn, user.user_id)
            if live >= settings.video_max_concurrent_sessions:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="too many active playback sessions",
                )

        viewer = Viewer(
            user_id=user.user_id,
            email=user.email,
            ip=request.client.host if request.client else None,
        )

        try:
            grant = await provider.issue_playback(context.video_id, viewer)
        except VideoProviderError as exc:
            # Upstream detail stays in the logs; the client gets a bare 502.
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="video service unavailable"
            ) from exc

        await learning.record_playback_session(
            conn,
            user_id=user.user_id,
            lesson_id=lesson_id,
            expires_at=grant.expires_at,
            ip=viewer.ip,
            user_agent=request.headers.get("user-agent"),
        )

    return PlaybackResponse(
        lesson_id=lesson_id,
        otp=grant.otp,
        playback_info=grant.playback_info,
        expires_at=grant.expires_at.isoformat(),
        direct_url=grant.direct_url,
    )

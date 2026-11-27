"""Playback grants.

This is the route the "no student downloads" requirement rests on. The sequence
is fixed and every step matters:

1. Authenticate the caller.
2. Check entitlement against the database -- enrollment active, not expired, or
   the lesson is a free preview.
3. Check the concurrent-session cap, so one shared login cannot serve a class.
4. Only then ask the provider for a short-lived, watermarked OTP.
5. Record the grant, so a watermarked leak can be traced to an account.

No stream URL is produced anywhere in this file. The browser receives an OTP
that expires in minutes and is useless to anyone else.

A YouTube lesson skips steps 3 to 5, and the reason is worth stating rather
than discovering: a YouTube video is public wherever it is embedded. There is
no OTP to mint, no watermark to burn in, and a concurrent-stream cap on a video
anyone can open on youtube.com protects nothing while still being able to lock
a legitimate student out of their own lesson. Performing those steps anyway
would be theatre, and theatre in a security path is worse than nothing because
it reads, later, like a guarantee. Step 2 is unchanged: a YouTube lesson inside
a gated course is still gated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.providers.video.base import VideoProviderError, Viewer
from app.repositories import learning
from app.security.deps import (
    CurrentUserDep,
    DatabaseDep,
    SettingsDep,
    VideoProviderDep,
    rate_limit,
    resolve_entitlement,
)
from app.security.ratelimit import Limits

router = APIRouter(prefix="/lessons", tags=["video"])

#: Minting an OTP is the most abusable route here: each one is a fresh licence
#: to play protected content.
_playback_limit = rate_limit("playback", Limits().playback)


class PlaybackResponse(BaseModel):
    lesson_id: UUID
    #: Which player the browser should render. "youtube" means the fields below
    #: carry no secret and `youtube_video_id` is set instead.
    provider: str
    otp: str
    playback_info: str
    expires_at: str
    #: Set only for a YouTube lesson. A public id, embedded in an iframe.
    youtube_video_id: str | None = None
    #: Populated only by the mock provider in development.
    direct_url: str | None = None
    #: Watch time already credited. The player seeds its counter from this and
    #: reports the running total, so re-watching from the start still adds to
    #: what came before instead of reporting a smaller number that credits
    #: nothing.
    watched_seconds: int = 0
    #: Where to resume from.
    last_position_seconds: int = 0


@router.post(
    "/{lesson_id}/playback",
    response_model=PlaybackResponse,
    dependencies=[Depends(_playback_limit)],
)
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

        if context.video_source == "youtube":
            # Nothing to protect and nothing to record: see the module docstring.
            # Progress is still tracked, by the heartbeat, exactly as elsewhere.
            stored = await learning.get_progress(conn, user.user_id, lesson_id)
            return PlaybackResponse(
                lesson_id=lesson_id,
                provider="youtube",
                youtube_video_id=context.video_id,
                # Deliberately empty rather than a plausible-looking value. A
                # fake OTP here would be indistinguishable from a real one in a
                # log, and the next person to read it would draw the wrong
                # conclusion about what this lesson is protected by.
                otp="",
                playback_info="",
                expires_at=datetime.now(UTC).isoformat(),
                watched_seconds=stored.watched_seconds if stored else 0,
                last_position_seconds=stored.last_position_seconds if stored else 0,
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

        stored = await learning.get_progress(conn, user.user_id, lesson_id)

    # Same reason as the upload URL: a relative path would resolve against the
    # frontend origin, where no such route exists.
    direct_url = grant.direct_url
    if direct_url and direct_url.startswith("/"):
        direct_url = str(request.base_url).rstrip("/") + direct_url

    return PlaybackResponse(
        lesson_id=lesson_id,
        provider=provider.name,
        otp=grant.otp,
        playback_info=grant.playback_info,
        expires_at=grant.expires_at.isoformat(),
        direct_url=direct_url,
        watched_seconds=stored.watched_seconds if stored else 0,
        last_position_seconds=stored.last_position_seconds if stored else 0,
    )

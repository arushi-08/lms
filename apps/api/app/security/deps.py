"""FastAPI dependencies for authentication and authorisation.

The division of labour, restated because it is easy to get wrong:

* The JWT is enough to know *who* someone is. ``current_user`` does no database
  work, so ordinary requests cost no extra round trip.
* The JWT is **not** enough to know whether someone is still an admin -- a token
  stays valid until it expires, so a demoted admin would keep their powers for
  up to an hour. ``require_admin`` therefore re-reads ``profiles.role``.
* Nothing here decides whether a student may watch a lesson. That is
  ``resolve_entitlement`` below, called by the routes that need it, so the check
  sits next to the thing it protects rather than in a decorator someone can
  forget to apply.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status

from app.config import Settings
from app.db import Database
from app.providers.video.base import VideoProvider
from app.repositories import learning
from app.security.jwt import (
    AAL_MULTI_FACTOR,
    AAL_SINGLE_FACTOR,
    InvalidToken,
    TokenClaims,
    bearer_token,
    verify_token,
)
from app.security.ratelimit import RateLimiter

logger = logging.getLogger("lms.auth")


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: UUID
    email: str
    claimed_role: str
    #: Assurance level from the token: one factor or two. See jwt.TokenClaims.
    aal: str = AAL_SINGLE_FACTOR

    @property
    def stepped_up(self) -> bool:
        return self.aal == AAL_MULTI_FACTOR


def get_db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def get_video_provider(request: Request) -> VideoProvider:
    provider: VideoProvider = request.app.state.video_provider
    return provider


def get_app_settings(request: Request) -> Settings:
    """The settings this app was built with -- not a module-level singleton.

    Reading a cached global here would mean a test (or a second app instance)
    could never configure the service it is actually exercising, and the
    mismatch shows up as a puzzling 401 rather than an obvious error.
    """
    settings: Settings = request.app.state.settings
    return settings


DatabaseDep = Annotated[Database, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
VideoProviderDep = Annotated[VideoProvider, Depends(get_video_provider)]


async def current_user(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    try:
        claims: TokenClaims = verify_token(bearer_token(authorization), settings)
    except InvalidToken as exc:
        # One message for every failure mode. Distinguishing "expired" from
        # "bad signature" tells an attacker which half of their guess was right.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return CurrentUser(
        user_id=claims.user_id,
        email=claims.email,
        claimed_role=claims.claimed_role,
        aal=claims.aal,
    )


#: Machine-readable reasons an admin request was refused for a second-factor
#: problem. The UI routes on these, so they are part of the interface: an admin
#: who has never enrolled needs the setup page, one who signed in with a single
#: factor needs the challenge page, and the two are not the same screen.
MFA_ENROLLMENT_REQUIRED = "mfa_enrollment_required"
MFA_REQUIRED = "mfa_required"
MFA_FACTOR_MISMATCH = "mfa_factor_mismatch"


async def require_admin(
    user: Annotated[CurrentUser, Depends(current_user)],
    database: Annotated[Database, Depends(get_db)],
) -> CurrentUser:
    """Admin, with a second factor, on the authenticator we expect.

    Four things must hold, and all four are checked here rather than spread
    across the routes, because a check that has to be remembered eventually is
    not.

    1. The database -- not the token -- says this account is an admin.
    2. The account has a pinned TOTP factor. An admin who has never enrolled has
       no admin powers; the only thing they can do is enroll.
    3. Its verified factors are *exactly* the pinned one. Passing this is what
       an attacker cannot arrange by enrolling an authenticator of their own.
    4. This session presented the second factor (``aal2``). Signing in with
       Google is one factor like a password is, so this is what stops OAuth from
       being a way around TOTP for an admin account.
    """
    async with database.acquire() as conn:
        context = await learning.get_admin_context(conn, user.user_id)

    if not context.is_admin:
        # Nothing about MFA is said here. A student probing admin routes learns
        # only that they are not an admin.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")

    if not context.has_pinned_factor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="two-factor authentication is required for admin access",
            headers={"X-MFA-Status": MFA_ENROLLMENT_REQUIRED},
        )

    if not context.factors_match_pin:
        # Either an unexpected authenticator was added, or the trusted one is
        # gone. Both need a human to look, so neither is a route the request can
        # talk its way out of.
        logger.warning(
            "admin %s has verified factors %s but trusts %s; refusing admin access",
            user.user_id,
            [str(f) for f in context.verified_factor_ids],
            context.pinned_factor_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="the authenticator on this account is not the expected one",
            headers={"X-MFA-Status": MFA_FACTOR_MISMATCH},
        )

    if not user.stepped_up:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="confirm your authenticator code to continue",
            headers={"X-MFA-Status": MFA_REQUIRED},
        )

    return user


def rate_limit(name: str, limit: int) -> Callable[..., Awaitable[None]]:
    """A per-user ceiling on one route.

    Keyed by user rather than IP: several students behind one office or campus
    NAT share an address, and limiting them as one would punish the innocent
    ones. Unauthenticated routes are not covered here — Supabase applies its own
    limits to sign-in and password reset.
    """

    async def dependency(
        request: Request,
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        window = request.app.state.rate_limit_window
        decision = limiter.check(f"{name}:{user.user_id}", limit=limit, window_seconds=window)

        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many requests; slow down",
                # Retry-After tells a well-behaved client exactly how long to
                # wait, instead of leaving it to guess and retry into the wall.
                headers={
                    "Retry-After": str(decision.retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

    return dependency


@dataclass(frozen=True, slots=True)
class Entitlement:
    context: learning.LessonContext
    is_admin: bool

    @property
    def enrollment_id(self) -> UUID | None:
        return self.context.enrollment_id


async def resolve_entitlement(
    conn: object,
    *,
    lesson_id: UUID,
    user: CurrentUser,
    require_enrollment: bool,
) -> Entitlement:
    """Decide whether this user may access this lesson, and say why not.

    ``require_enrollment=False`` is for playback, where a lesson flagged as a
    free preview is deliberately open. Progress and quizzes pass True, because
    both write rows that hang off an enrollment.
    """
    context = await learning.get_lesson_context(conn, lesson_id, user.user_id)  # type: ignore[arg-type]
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lesson not found")

    admin = await learning.get_admin_context(conn, user.user_id)  # type: ignore[arg-type]
    # The same bar as require_admin, not a softer one. Admin here buys a look at
    # unpublished content, and an admin session that has not presented its second
    # factor should not get that either -- otherwise "admin powers need TOTP"
    # would have a quiet exception in the one place it is easiest to miss.
    is_admin = admin.is_admin and admin.factors_match_pin and user.stepped_up

    if context.course_status != "published" and not is_admin:
        # 404 rather than 403: an unpublished course should not be discoverable
        # by probing lesson ids.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lesson not found")

    if is_admin:
        return Entitlement(context=context, is_admin=True)

    if context.has_live_enrollment:
        return Entitlement(context=context, is_admin=False)

    if not require_enrollment and context.is_preview:
        return Entitlement(context=context, is_admin=False)

    # Distinguish "you never had access" from "your access ran out", because the
    # two need different things from the student and neither reveals anything
    # they could not already see on the course page.
    if context.enrollment_id is not None and not context.has_live_enrollment:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access expired")

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not enrolled")


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]
AdminDep = Annotated[CurrentUser, Depends(require_admin)]

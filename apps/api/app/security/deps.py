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

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status

from app.config import Settings
from app.db import Database
from app.providers.video.base import VideoProvider
from app.repositories import learning
from app.security.jwt import InvalidToken, TokenClaims, bearer_token, verify_token


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: UUID
    email: str
    claimed_role: str


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
        user_id=claims.user_id, email=claims.email, claimed_role=claims.claimed_role
    )


async def require_admin(
    user: Annotated[CurrentUser, Depends(current_user)],
    database: Annotated[Database, Depends(get_db)],
) -> CurrentUser:
    async with database.acquire() as conn:
        role = await learning.get_profile_role(conn, user.user_id)

    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return user


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
    both write rows that hang off an enrolment.
    """
    context = await learning.get_lesson_context(conn, lesson_id, user.user_id)  # type: ignore[arg-type]
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lesson not found")

    role = await learning.get_profile_role(conn, user.user_id)  # type: ignore[arg-type]
    is_admin = role == "admin"

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

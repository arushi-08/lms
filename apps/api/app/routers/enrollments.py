"""Student self-enrollment.

Only free courses. A paid course is entered through the payment provider's
webhook, never through a request the browser can make — otherwise the price is
a suggestion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.domain.progress import resolve_expiry
from app.repositories import learning
from app.security.deps import CurrentUserDep, DatabaseDep, rate_limit
from app.security.ratelimit import Limits

router = APIRouter(prefix="/enrollments", tags=["enrollments"])

_limit = rate_limit("enrollment", Limits().enrollment)


class EnrollRequest(BaseModel):
    course_slug: str = Field(min_length=1, max_length=200)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(_limit)])
async def enroll(
    payload: EnrollRequest, user: CurrentUserDep, database: DatabaseDep
) -> dict[str, Any]:
    async with database.transaction() as conn:
        course = await learning.get_course_by_slug(conn, payload.course_slug)
        if course is None or course.status != "published":
            # 404 for an unpublished course as well: its existence is not public.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="course not found"
            )
        if not course.is_free:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="this course must be purchased",
            )

        expires_at = resolve_expiry(
            access_type=course.access_type,
            access_days=course.access_days,
            enrolled_at=datetime.now(UTC),
        )
        enrollment = await learning.self_enroll(
            conn, user_id=user.user_id, course_id=course.course_id, expires_at=expires_at
        )

    return {**enrollment, "id": str(enrollment["id"])}

"""Admin second-factor status and authenticator rotation.

Deliberately small. Supabase does enrollment, the QR code, the challenge and the
code check; this service holds no TOTP secret and verifies no code. What is left
is two things Supabase cannot answer for us:

* **Status.** Not "does this account have a factor" -- the browser can ask
  Supabase that -- but "would an admin request from this session be allowed, and
  if not, why". The comparison that decides it lives in one place (the admin
  gate), and this route reports that same verdict so the UI cannot drift into a
  second, kinder opinion of its own.
* **Rotation.** Moving to a new phone. The pinned authenticator is what makes an
  ``aal2`` token trustworthy, so replacing it has to be an explicit act by a
  session that has already used the current one.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.repositories import admin as audit
from app.repositories import learning
from app.security.deps import (
    MFA_ENROLLMENT_REQUIRED,
    MFA_FACTOR_MISMATCH,
    MFA_REQUIRED,
    AdminDep,
    CurrentUser,
    CurrentUserDep,
    DatabaseDep,
    rate_limit,
)
from app.security.ratelimit import Limits

router = APIRouter(prefix="/admin/mfa", tags=["admin"])

_limit = rate_limit("mfa", Limits().admin_writes)


class MfaStatus(BaseModel):
    #: True only when an admin request from this session would be allowed.
    satisfied: bool
    #: One of the MFA_* codes, or None when satisfied. What the UI routes on.
    reason: str | None
    enrolled: bool
    stepped_up: bool
    #: How many TOTP factors are verified. More than one is a problem, not a
    #: convenience: see the admin gate for why.
    verified_factor_count: int


async def _require_admin_role(
    user: CurrentUserDep,
    database: DatabaseDep,
) -> tuple[CurrentUser, learning.AdminContext]:
    """Admin by role, with no second-factor requirement.

    The status route needs this weaker check by design: an admin who is blocked
    has to be able to find out why. It reveals only the account's own MFA state
    to the account itself, and grants no authority over anything else.
    """
    async with database.acquire() as conn:
        context = await learning.get_admin_context(conn, user.user_id)
    if not context.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return user, context


@router.get("", response_model=MfaStatus, dependencies=[Depends(_limit)])
async def mfa_status(
    both: Annotated[
        tuple[CurrentUser, learning.AdminContext], Depends(_require_admin_role)
    ],
) -> MfaStatus:
    user, context = both

    if not context.has_pinned_factor:
        reason: str | None = MFA_ENROLLMENT_REQUIRED
    elif not context.factors_match_pin:
        reason = MFA_FACTOR_MISMATCH
    elif not user.stepped_up:
        reason = MFA_REQUIRED
    else:
        reason = None

    return MfaStatus(
        satisfied=reason is None,
        reason=reason,
        enrolled=context.has_pinned_factor,
        stepped_up=user.stepped_up,
        verified_factor_count=len(context.verified_factor_ids),
    )


class RotateResult(BaseModel):
    #: The factor that was trusted until now, for the record.
    previous_factor_id: UUID | None


@router.post("/rotate", response_model=RotateResult, dependencies=[Depends(_limit)])
async def rotate_authenticator(
    request: Request,
    user: AdminDep,
    database: DatabaseDep,
) -> RotateResult:
    """Un-pin the current authenticator so the next one verified is trusted.

    Guarded by the full admin gate, which means this session has just used the
    current authenticator. That is the point: consenting to replace a factor
    requires possession of it. An admin who has *lost* their factor cannot reach
    this route -- and must not be able to, or losing the phone would be the
    easiest way in. Recovery is scripts/reset_admin_mfa.py, run by someone with
    database access.

    Rotation leaves the account with no trusted factor, so admin access stays
    closed until a new one is enrolled and verified. Locked-until-fixed is the
    correct state to land in.
    """
    async with database.transaction() as conn:
        context = await learning.get_admin_context(conn, user.user_id)
        await learning.clear_pinned_factor(conn, user.user_id)
        await audit.write_audit(
            conn,
            actor_id=user.user_id,
            action="mfa.rotation_started",
            entity_type="profile",
            entity_id=str(user.user_id),
            diff={"unpinned_factor_id": str(context.pinned_factor_id)},
            ip=request.client.host if request.client else None,
        )
    return RotateResult(previous_factor_id=context.pinned_factor_id)

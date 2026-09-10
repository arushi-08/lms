"""Supabase JWT verification.

Supabase issues the token; this service only verifies it. Two signing schemes
exist in the wild and both are supported: newer projects sign asymmetrically and
publish a JWKS, older ones use a shared HS256 secret. Asymmetric is preferred --
it means this service holds no key capable of *minting* a token, only of
checking one.

Verification is strict on purpose. Signature, expiry, audience and issuer are
all checked, because each unchecked claim is a way in: an unverified signature
accepts anything, an unchecked ``aud`` accepts tokens Supabase minted for a
different purpose, and an unchecked ``iss`` accepts tokens from someone else's
Supabase project entirely.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient

from app.config import Settings

logger = logging.getLogger("lms.auth")


class InvalidToken(Exception):
    """The token is absent, malformed, expired, or not ours."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: UUID
    email: str
    #: Role as asserted by the token. Good enough for read paths; admin routes
    #: re-read the database, because a revoked admin keeps a valid token until
    #: it expires.
    claimed_role: str


class ResilientJWKClient:
    """A JWKS client that survives the key server being briefly unreachable.

    Without this, a failed key fetch fails *every* authenticated request — the
    service is down while the database is perfectly healthy, and nothing in the
    application is actually broken. Since signing keys rotate rarely and a key
    we have already verified against stays valid, the right behaviour during an
    outage is to keep using the last good one and complain loudly.

    A key we have never seen still fails: serving an unknown key from nowhere
    would mean accepting tokens we cannot verify, which is the opposite of the
    point.
    """

    def __init__(self, jwks_url: str) -> None:
        self._client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
        self._last_good: dict[str, Any] = {}

    def signing_key_for(self, token: str) -> Any:
        try:
            key = self._client.get_signing_key_from_jwt(token)
        except Exception as exc:
            kid = self._kid(token)
            cached = self._last_good.get(kid) if kid else None
            if cached is None:
                raise
            # Loud, because this is a real upstream problem even though requests
            # keep succeeding. Silence here would hide an outage until keys
            # rotate and everything fails at once.
            logger.warning(
                "JWKS fetch failed (%s); serving the last known key for kid=%s",
                type(exc).__name__,
                kid,
            )
            return cached

        kid = self._kid(token)
        if kid:
            self._last_good[kid] = key.key
        return key.key

    @staticmethod
    def _kid(token: str) -> str | None:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            return None
        kid = header.get("kid")
        return kid if isinstance(kid, str) else None


@lru_cache(maxsize=4)
def _jwk_client(jwks_url: str) -> ResilientJWKClient:
    # One client per URL; it holds the key cache and the last-good fallback.
    return ResilientJWKClient(jwks_url)


def _decode(token: str, settings: Settings) -> dict[str, object]:
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"
    options = {"require": ["exp", "sub"]}

    secret = settings.supabase_jwt_secret
    if secret is not None and secret.get_secret_value():
        return jwt.decode(
            token,
            secret.get_secret_value(),
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=issuer,
            options=options,
        )

    signing_key = _jwk_client(f"{issuer}/.well-known/jwks.json").signing_key_for(token)
    return jwt.decode(
        token,
        signing_key,
        algorithms=["RS256", "ES256"],
        audience=settings.jwt_audience,
        issuer=issuer,
        options=options,
    )


def verify_token(token: str, settings: Settings) -> TokenClaims:
    if not token:
        raise InvalidToken("no token supplied")

    try:
        payload = _decode(token, settings)
    except jwt.ExpiredSignatureError as exc:
        raise InvalidToken("token expired") from exc
    except jwt.InvalidTokenError as exc:
        # Covers bad signature, wrong audience, wrong issuer, malformed input.
        # The reason is deliberately not echoed to the client.
        raise InvalidToken("token rejected") from exc
    except Exception as exc:  # JWKS fetch failure, unexpected key material
        raise InvalidToken("token could not be verified") from exc

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise InvalidToken("token has no subject")

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise InvalidToken("token subject is not a user id") from exc

    email = payload.get("email")
    role = payload.get("user_role")

    return TokenClaims(
        user_id=user_id,
        email=email if isinstance(email, str) else "",
        # Absent claim means the access-token hook is not enabled. Default to
        # the least privilege rather than guessing.
        claimed_role=role if isinstance(role, str) else "student",
    )


def bearer_token(authorization: str | None) -> str:
    """Pull the token out of an Authorization header, strictly."""
    if not authorization:
        raise InvalidToken("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise InvalidToken("Authorization header must be a bearer token")
    return token.strip()

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

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
from jwt import PyJWKClient

from app.config import Settings


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


@lru_cache(maxsize=4)
def _jwk_client(jwks_url: str) -> PyJWKClient:
    # PyJWKClient caches fetched keys internally; one client per URL is enough.
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


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

    signing_key = _jwk_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
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

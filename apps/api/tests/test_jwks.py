"""JWKS resilience tests.

The failure this guards against is the nastiest kind: the database is healthy,
the code is correct, nothing is deployed -- and every authenticated request
returns 401 because one HTTPS fetch to the key server timed out.
"""

from __future__ import annotations

from typing import Any

import jwt
import pytest

from app.security.jwt import ResilientJWKClient


class _FakeKey:
    def __init__(self, material: str) -> None:
        self.key = material


class _FakeUpstream:
    """Stands in for PyJWKClient: hands out a key, or refuses to."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.fail = False
        self.calls = 0

    def get_signing_key_from_jwt(self, token: str) -> Any:
        self.calls += 1
        if self.fail:
            raise ConnectionError("jwks unreachable")
        return _FakeKey(self.key)


#: Only ever used to produce a well-formed header; nothing here verifies a
#: signature. Long enough to keep PyJWT from warning about key length.
_SIGNING_SECRET = "test-only-secret-at-least-32-bytes-long"


def _token(kid: str | None) -> str:
    headers = {"kid": kid} if kid else {}
    return jwt.encode({"sub": "x"}, _SIGNING_SECRET, algorithm="HS256", headers=headers)


@pytest.fixture
def client_and_upstream() -> tuple[ResilientJWKClient, _FakeUpstream]:
    client = ResilientJWKClient("http://localhost/.well-known/jwks.json")
    upstream = _FakeUpstream("key-material-v1")
    client._client = upstream  # type: ignore[assignment]
    return client, upstream


class TestResilientJWKClient:
    def test_it_returns_the_fetched_key(self, client_and_upstream) -> None:
        client, _ = client_and_upstream
        assert client.signing_key_for(_token("kid-1")) == "key-material-v1"

    def test_a_later_outage_is_survived(self, client_and_upstream) -> None:
        client, upstream = client_and_upstream
        token = _token("kid-1")
        assert client.signing_key_for(token) == "key-material-v1"

        upstream.fail = True
        # Same key, still valid: an unreachable key server is not a reason to
        # stop trusting tokens we could verify a second ago.
        assert client.signing_key_for(token) == "key-material-v1"

    def test_it_warns_while_serving_a_cached_key(
        self, client_and_upstream, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Loud, because requests keep succeeding. Silence here would hide the
        outage until keys rotate and then everything fails at once."""
        client, upstream = client_and_upstream
        token = _token("kid-1")
        client.signing_key_for(token)

        upstream.fail = True
        with caplog.at_level("WARNING", logger="lms.auth"):
            client.signing_key_for(token)
        assert any("JWKS" in record.message for record in caplog.records)

    def test_an_unknown_key_still_fails(self, client_and_upstream) -> None:
        """The fallback serves keys we have verified against before. Inventing
        one for an unseen kid would mean accepting tokens we cannot check --
        exactly the thing verification exists to prevent."""
        client, upstream = client_and_upstream
        client.signing_key_for(_token("kid-1"))

        upstream.fail = True
        with pytest.raises(ConnectionError):
            client.signing_key_for(_token("kid-2-never-seen"))

    def test_a_token_with_no_kid_is_not_served_from_cache(
        self, client_and_upstream
    ) -> None:
        client, upstream = client_and_upstream
        client.signing_key_for(_token("kid-1"))

        upstream.fail = True
        with pytest.raises(ConnectionError):
            client.signing_key_for(_token(None))

    def test_rotation_replaces_the_cached_key(self, client_and_upstream) -> None:
        client, upstream = client_and_upstream
        client.signing_key_for(_token("kid-1"))

        upstream.key = "key-material-v2"
        assert client.signing_key_for(_token("kid-1")) == "key-material-v2"
        upstream.fail = True
        # The fallback follows rotation rather than pinning the first key it saw.
        assert client.signing_key_for(_token("kid-1")) == "key-material-v2"

    def test_garbage_is_rejected_without_a_cache_lookup(
        self, client_and_upstream
    ) -> None:
        client, upstream = client_and_upstream
        client.signing_key_for(_token("kid-1"))

        upstream.fail = True
        with pytest.raises(ConnectionError):
            client.signing_key_for("not-a-jwt")

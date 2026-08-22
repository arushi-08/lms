"""Video providers: the request VdoCipher actually receives, and mock parity."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest

from app.config import Settings
from app.providers.video.base import VideoProviderError, Viewer
from app.providers.video.factory import build_video_provider
from app.providers.video.mock import MockVideoProvider
from app.providers.video.vdocipher import VdoCipherProvider, build_watermark

VIEWER = Viewer(
    user_id=UUID("11111111-1111-1111-1111-111111111111"),
    email="alice@example.test",
    ip="203.0.113.7",
)


def client_returning(
    payload: dict[str, object], status: int = 200, captured: list[httpx.Request] | None = None
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestWatermark:
    def test_carries_the_viewer_identity(self) -> None:
        annotation = json.loads(build_watermark(VIEWER))
        text = annotation[0]["text"]
        assert "alice@example.test" in text
        assert "11111111" in text

    def test_is_the_shape_vdocipher_expects(self) -> None:
        annotation = json.loads(build_watermark(VIEWER))
        assert isinstance(annotation, list)
        assert annotation[0]["type"] == "rtext"
        assert {"alpha", "color", "size", "interval"} <= annotation[0].keys()


class TestVdoCipherPlayback:
    async def test_sends_secret_ttl_and_watermark(self) -> None:
        captured: list[httpx.Request] = []
        provider = VdoCipherProvider(
            "top-secret",
            otp_ttl_seconds=120,
            client=client_returning({"otp": "OTP123", "playbackInfo": "PB456"}, captured=captured),
        )

        grant = await provider.issue_playback("vid-1", VIEWER)

        request = captured[0]
        assert request.method == "POST"
        assert request.url.path.endswith("/videos/vid-1/otp")
        assert request.headers["Authorization"] == "Apisecret top-secret"

        body = json.loads(request.content)
        assert body["ttl"] == 120
        assert "alice@example.test" in body["annotate"]

        assert grant.otp == "OTP123"
        assert grant.playback_info == "PB456"
        # No stream URL is ever produced on our side.
        assert grant.direct_url is None

    async def test_watermark_can_be_disabled(self) -> None:
        captured: list[httpx.Request] = []
        provider = VdoCipherProvider(
            "s",
            watermark_enabled=False,
            client=client_returning({"otp": "a", "playbackInfo": "b"}, captured=captured),
        )
        await provider.issue_playback("vid-1", VIEWER)
        assert "annotate" not in json.loads(captured[0].content)

    async def test_grant_expiry_reflects_the_configured_ttl(self) -> None:
        # A grant that outlives its OTP would have the UI show a working player
        # that 403s on play; a grant that expires early causes needless retries.
        provider = VdoCipherProvider(
            "s", otp_ttl_seconds=300,
            client=client_returning({"otp": "a", "playbackInfo": "b"}),
        )
        before = datetime.now(UTC)
        grant = await provider.issue_playback("vid-1", VIEWER)
        after = datetime.now(UTC)

        assert before + timedelta(seconds=300) <= grant.expires_at <= after + timedelta(seconds=300)

    async def test_short_ttl_is_honoured(self) -> None:
        provider = VdoCipherProvider(
            "s", otp_ttl_seconds=60,
            client=client_returning({"otp": "a", "playbackInfo": "b"}),
        )
        grant = await provider.issue_playback("vid-1", VIEWER)
        assert (grant.expires_at - datetime.now(UTC)).total_seconds() <= 60


class TestVdoCipherFailures:
    async def test_http_error_does_not_leak_the_api_secret(self) -> None:
        provider = VdoCipherProvider(
            "top-secret", client=client_returning({"message": "nope"}, status=403)
        )
        with pytest.raises(VideoProviderError) as exc:
            await provider.issue_playback("vid-1", VIEWER)
        assert "top-secret" not in str(exc.value)
        assert "403" in str(exc.value)

    async def test_malformed_response_is_rejected_not_passed_through(self) -> None:
        provider = VdoCipherProvider("s", client=client_returning({"otp": "only-half"}))
        with pytest.raises(VideoProviderError, match="missing required fields"):
            await provider.issue_playback("vid-1", VIEWER)

    async def test_transport_error_is_wrapped(self) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns", request=request)

        provider = VdoCipherProvider(
            "top-secret", client=httpx.AsyncClient(transport=httpx.MockTransport(boom))
        )
        with pytest.raises(VideoProviderError) as exc:
            await provider.issue_playback("vid-1", VIEWER)
        assert "top-secret" not in str(exc.value)


class TestMockProvider:
    async def test_two_viewers_never_share_a_grant(self) -> None:
        provider = MockVideoProvider()
        other = Viewer(UUID("22222222-2222-2222-2222-222222222222"), "bob@example.test")
        first = await provider.issue_playback("vid-1", VIEWER)
        second = await provider.issue_playback("vid-1", other)
        assert first.otp != second.otp

    async def test_repeat_grants_to_one_viewer_are_also_distinct(self) -> None:
        provider = MockVideoProvider()
        a = await provider.issue_playback("vid-1", VIEWER)
        b = await provider.issue_playback("vid-1", VIEWER)
        assert a.otp != b.otp

    async def test_upload_then_processing_then_ready(self) -> None:
        # The admin UI has to render a "still encoding" state; the mock produces
        # one so that path is exercised before the real account exists.
        provider = MockVideoProvider()
        ticket = await provider.create_upload("Lesson 1")
        assert ticket.video_id.startswith("mock-")
        assert await provider.get_status(ticket.video_id) == "processing"

    async def test_unknown_video_reads_as_ready(self) -> None:
        assert await MockVideoProvider().get_status("seeded-video") == "ready"

    async def test_empty_video_id_is_an_error(self) -> None:
        with pytest.raises(VideoProviderError):
            await MockVideoProvider().issue_playback("", VIEWER)


class TestFactory:
    def test_development_gets_the_mock(self) -> None:
        assert build_video_provider(Settings()).name == "mock"

    def test_configured_vdocipher_gets_the_real_one(self) -> None:
        from pydantic import SecretStr

        settings = Settings(video_provider="vdocipher", vdocipher_api_secret=SecretStr("s"))
        assert build_video_provider(settings).name == "vdocipher"

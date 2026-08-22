"""Selects the video provider from configuration."""

from __future__ import annotations

from app.config import Settings
from app.providers.video.base import VideoProvider
from app.providers.video.mock import MockVideoProvider
from app.providers.video.vdocipher import VdoCipherProvider


def build_video_provider(settings: Settings) -> VideoProvider:
    if settings.video_provider == "vdocipher":
        secret = settings.vdocipher_api_secret
        if secret is None:  # pragma: no cover - Settings validation covers this
            raise RuntimeError("VDOCIPHER_API_SECRET missing")
        return VdoCipherProvider(
            api_secret=secret.get_secret_value(),
            base_url=settings.vdocipher_api_base,
            otp_ttl_seconds=settings.vdocipher_otp_ttl_seconds,
            watermark_enabled=settings.video_watermark_enabled,
        )
    return MockVideoProvider(otp_ttl_seconds=settings.vdocipher_otp_ttl_seconds)

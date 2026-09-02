"""Application settings.

Everything comes from the environment; nothing is hardcoded and nothing has a
usable production default. Where a missing value would silently degrade
security -- a mock video provider in production, a missing VdoCipher secret --
startup fails loudly instead. A server that boots into an insecure
configuration is worse than one that refuses to boot.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Anchored to this package, not the working directory. A relative ".env" is
#: resolved against wherever the process happens to have been started, so the
#: service would load no configuration at all when launched from the repo root
#: -- and then fail with a confusing database error rather than a missing-config
#: one, because empty settings still look valid.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

Environment = Literal["development", "staging", "production"]
VideoProviderName = Literal["mock", "vdocipher"]
PaymentProviderName = Literal["none", "stripe"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = "development"
    log_level: str = "INFO"

    # --- Supabase -----------------------------------------------------------
    supabase_url: str = "http://localhost:54321"
    #: Public by design. Safe only because RLS is enabled on every table.
    supabase_anon_key: str = ""
    #: Bypasses RLS. Server-side only -- must never reach a browser bundle.
    supabase_service_role_key: SecretStr = SecretStr("")
    #: Legacy HS256 projects only. Newer projects verify via JWKS instead.
    supabase_jwt_secret: SecretStr | None = None
    jwt_audience: str = "authenticated"

    database_url: SecretStr = SecretStr("")
    database_pool_min: int = 1
    database_pool_max: int = 5

    # --- HTTP ---------------------------------------------------------------
    #: Exact origins. No wildcard: credentials are sent cross-origin.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    api_base_path: str = "/api"

    # --- Video --------------------------------------------------------------
    video_provider: VideoProviderName = "mock"
    vdocipher_api_secret: SecretStr | None = None
    vdocipher_api_base: str = "https://dev.vdocipher.com/api"
    #: Short enough that a leaked OTP is worthless before it can be shared.
    vdocipher_otp_ttl_seconds: int = 300
    #: Identifies the leaker if DRM-protected content escapes anyway.
    video_watermark_enabled: bool = True
    #: Simultaneous playback grants per user before requests are refused.
    video_max_concurrent_sessions: int = 2

    # --- Payments -----------------------------------------------------------
    # "none" for the pilot: Stripe is not approved yet and no price is set.
    payment_provider: PaymentProviderName = "none"
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None

    # --- Observability ------------------------------------------------------
    sentry_dsn: str | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _check_coherent(self) -> Settings:
        if self.video_provider == "vdocipher" and not self.vdocipher_api_secret:
            raise ValueError("VDOCIPHER_API_SECRET is required when VIDEO_PROVIDER=vdocipher")

        if self.payment_provider == "stripe" and not (
            self.stripe_secret_key and self.stripe_webhook_secret
        ):
            raise ValueError(
                "STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are required "
                "when PAYMENT_PROVIDER=stripe"
            )

        if self.is_production:
            # Each of these would be an outage or a breach if it slipped through
            # a deploy unnoticed, and each is trivially checkable here.
            if self.video_provider == "mock":
                raise ValueError("the mock video provider must not run in production")
            if not self.supabase_service_role_key.get_secret_value():
                raise ValueError("SUPABASE_SERVICE_ROLE_KEY is required in production")
            if not self.database_url.get_secret_value():
                raise ValueError("DATABASE_URL is required in production")
            if any(o.startswith("http://") for o in self.cors_origins):
                raise ValueError("plaintext http origins are not allowed in production")
            if "*" in self.cors_origins:
                raise ValueError("wildcard CORS origin is not allowed")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

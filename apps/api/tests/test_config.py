"""Settings validation -- the fail-fast guards, not the plumbing."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def prod(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "production",
        "video_provider": "vdocipher",
        "vdocipher_api_secret": SecretStr("secret"),
        "supabase_service_role_key": SecretStr("service-key"),
        "database_url": SecretStr("postgresql://user:pw@host/db"),
        "cors_origins": ["https://app.example.com"],
    }
    return Settings(**(base | overrides))  # type: ignore[arg-type]


class TestProviderCoherence:
    def test_vdocipher_without_a_secret_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="VDOCIPHER_API_SECRET"):
            Settings(video_provider="vdocipher")

    def test_stripe_without_keys_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="STRIPE_SECRET_KEY"):
            Settings(payment_provider="stripe")

    def test_development_defaults_to_the_mock_provider(self) -> None:
        assert Settings().video_provider == "mock"
        assert Settings().payment_provider == "none"


class TestProductionGuards:
    def test_a_valid_production_config_is_accepted(self) -> None:
        assert prod().is_production

    def test_mock_video_provider_cannot_reach_production(self) -> None:
        # The whole point of the mock is that it skips DRM. Shipping it would
        # serve every course unprotected, and nothing else would look wrong.
        with pytest.raises(ValidationError, match="mock video provider"):
            prod(video_provider="mock", vdocipher_api_secret=None)

    def test_missing_service_role_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="SERVICE_ROLE_KEY"):
            prod(supabase_service_role_key=SecretStr(""))

    def test_missing_database_url_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="DATABASE_URL"):
            prod(database_url=SecretStr(""))

    def test_plaintext_origin_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="plaintext http"):
            prod(cors_origins=["http://app.example.com"])

    def test_wildcard_origin_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="wildcard"):
            prod(cors_origins=["*"])


class TestSecretHandling:
    def test_secrets_do_not_appear_in_repr(self) -> None:
        # Settings get logged and dumped into error reports; a plain str field
        # would put the service role key in Sentry.
        settings = prod()
        assert "service-key" not in repr(settings)
        assert "secret" not in repr(settings.vdocipher_api_secret)

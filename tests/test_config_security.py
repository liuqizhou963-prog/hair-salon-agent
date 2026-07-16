import pytest

from backend.config import DEFAULT_AUTH_SECRET_KEY, Settings, validate_security_settings


def _production_config() -> Settings:
    config = Settings()
    config.APP_ENV = "production"
    config.DEBUG = False
    config.AUTH_SECRET_KEY = "a" * 40
    config.CORS_ALLOWED_ORIGINS = ["https://salon.example.com"]
    config.DATABASE_URL = "postgresql://user:password@db:5432/salon"
    config.RATE_LIMIT_ENABLED = True
    config.DEMO_MODE = False
    return config


def test_production_security_config_accepts_explicit_values():
    validate_security_settings(_production_config())


@pytest.mark.parametrize(
    "field,value",
    [
        ("AUTH_SECRET_KEY", DEFAULT_AUTH_SECRET_KEY),
        ("CORS_ALLOWED_ORIGINS", ["*"]),
        ("DATABASE_URL", "sqlite:///demo.db"),
        ("DEMO_MODE", True),
    ],
)
def test_production_security_config_rejects_demo_values(field, value):
    config = _production_config()
    setattr(config, field, value)

    with pytest.raises(RuntimeError, match="Production security checks failed"):
        validate_security_settings(config)


def test_development_security_config_keeps_demo_mode_available():
    config = Settings()
    config.APP_ENV = "development"
    config.AUTH_SECRET_KEY = DEFAULT_AUTH_SECRET_KEY

    validate_security_settings(config)

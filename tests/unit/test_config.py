import os

import pytest

from distributed_job_queue.common.config import ConfigurationError, load_settings


def test_load_settings_uses_development_defaults():
    settings = load_settings()

    assert settings.environment == "development"
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 8000
    assert settings.database_url.startswith("postgresql+")
    assert settings.job_lease_seconds == 60
    assert settings.worker_long_poll_seconds == 20
    assert settings.worker_gateway_url == "http://localhost:8000"
    assert settings.worker_gateway_token == "dev-worker-token"
    assert settings.max_attempts == 5
    assert settings.outbox_batch_size == 100
    assert settings.outbox_poll_interval_seconds == 1
    assert settings.scheduler_batch_size == 100
    assert settings.scheduler_poll_interval_seconds == 1
    assert settings.recovery_batch_size == 100
    assert settings.recovery_poll_interval_seconds == 1


def test_load_settings_parses_environment_values(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "9000")
    monkeypatch.setenv("JOB_LEASE_SECONDS", "90")
    monkeypatch.setenv("WORKER_LONG_POLL_SECONDS", "15")
    monkeypatch.setenv("WORKER_GATEWAY_TOKEN", "test-worker-token")
    monkeypatch.setenv("WORKER_GATEWAY_URL", "https://queue.example.com")
    monkeypatch.setenv("MAX_ATTEMPTS", "3")
    monkeypatch.setenv("SCHEDULER_BATCH_SIZE", "25")
    monkeypatch.setenv("SCHEDULER_POLL_INTERVAL_SECONDS", "2")
    monkeypatch.setenv("RECOVERY_BATCH_SIZE", "30")
    monkeypatch.setenv("RECOVERY_POLL_INTERVAL_SECONDS", "3")

    settings = load_settings()

    assert settings.environment == "test"
    assert settings.debug is True
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 9000
    assert settings.job_lease_seconds == 90
    assert settings.worker_long_poll_seconds == 15
    assert settings.worker_gateway_token == "test-worker-token"
    assert settings.worker_gateway_url == "https://queue.example.com"
    assert settings.max_attempts == 3
    assert settings.scheduler_batch_size == 25
    assert settings.scheduler_poll_interval_seconds == 2
    assert settings.recovery_batch_size == 30
    assert settings.recovery_poll_interval_seconds == 3


def test_load_settings_rejects_invalid_integer(monkeypatch):
    monkeypatch.setenv("MAX_ATTEMPTS", "many")

    with pytest.raises(ConfigurationError, match="MAX_ATTEMPTS"):
        load_settings()


def test_load_settings_rejects_invalid_boolean(monkeypatch):
    monkeypatch.setenv("APP_DEBUG", "sometimes")

    with pytest.raises(ConfigurationError, match="APP_DEBUG"):
        load_settings()


def test_load_settings_requires_worker_token_outside_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("WORKER_GATEWAY_TOKEN", raising=False)

    with pytest.raises(ConfigurationError, match="WORKER_GATEWAY_TOKEN"):
        load_settings()

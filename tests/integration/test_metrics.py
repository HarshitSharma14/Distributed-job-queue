import asyncio
from uuid import uuid4

import httpx
import pytest

from distributed_job_queue.api.app import app


def request(path: str, *, token: str | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get(path, headers=headers)

    return asyncio.run(send())


@pytest.fixture(autouse=True)
def metrics_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("METRICS_TOKEN", "integration-metrics-token")


def test_metrics_endpoint_requires_separate_bearer_token():
    response = request("/metrics")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "METRICS_UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


def test_metrics_endpoint_exposes_platform_and_template_labeled_http_metrics():
    job_id = str(uuid4())
    not_found = request(f"/jobs/{job_id}")
    assert not_found.status_code == 404

    response = request("/metrics", token="integration-metrics-token")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "djq_http_requests_total" in body
    assert 'route="/jobs/{job_id}"' in body
    assert job_id not in body
    assert "djq_jobs_submitted_total" in body
    assert "djq_queue_depth" in body
    assert 'djq_state_collector_up{source="postgresql"} 1.0' in body
    assert 'djq_state_collector_up{source="redis"} 1.0' in body

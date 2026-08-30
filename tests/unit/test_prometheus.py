from datetime import datetime, timezone

import httpx

from distributed_job_queue.common.prometheus import PrometheusQueryClient


def test_dashboard_queries_are_allowlisted_and_hide_target_labels():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [
                        {
                            "metric": {
                                "queue": "reports",
                                "outcome": "COMPLETED",
                                "instance": "private-api:8000",
                                "job": "private-api",
                            },
                            "values": [[1_777_507_200, "2.5"]],
                        }
                    ],
                },
            },
        )

    client = PrometheusQueryClient("http://prometheus:9090")
    client._client.close()
    client._client = httpx.Client(
        base_url="http://prometheus:9090",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.dashboard_trends(
            "1h", datetime(2026, 5, 1, tzinfo=timezone.utc)
        )
    finally:
        client.close()

    assert len(requests) == 8
    assert all(request.url.path == "/api/v1/query_range" for request in requests)
    assert all(request.url.params["step"] == "60" for request in requests)
    submission = next(
        series for series in result.series if series.key == "job_submission_rate"
    )
    assert submission.labels == {"queue": "reports"}
    assert submission.points[0].value == 2.5
    assert "instance" not in submission.labels
    assert "job" not in submission.labels

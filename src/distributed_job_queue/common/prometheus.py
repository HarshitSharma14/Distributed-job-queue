"""Read-only, allowlisted Prometheus queries for the Admin dashboard."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx


class PrometheusQueryError(RuntimeError):
    """Raised when Prometheus cannot return a valid range query."""


@dataclass(frozen=True, slots=True)
class TrendWindow:
    duration: timedelta
    step_seconds: int
    rate_range: str


TREND_WINDOWS = {
    "1h": TrendWindow(timedelta(hours=1), 60, "5m"),
    "6h": TrendWindow(timedelta(hours=6), 300, "10m"),
    "24h": TrendWindow(timedelta(hours=24), 900, "15m"),
    "7d": TrendWindow(timedelta(days=7), 3600, "1h"),
}


@dataclass(frozen=True, slots=True)
class TrendQuery:
    key: str
    unit: str
    expression: str
    visible_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrendPoint:
    timestamp: datetime
    value: float | None


@dataclass(frozen=True, slots=True)
class TrendSeries:
    key: str
    unit: str
    labels: dict[str, str]
    points: list[TrendPoint]


@dataclass(frozen=True, slots=True)
class TrendResult:
    start: datetime
    end: datetime
    step_seconds: int
    series: list[TrendSeries]


def _queries(rate_range: str) -> tuple[TrendQuery, ...]:
    return (
        TrendQuery(
            "job_submission_rate",
            "jobs_per_second",
            f"sum(rate(djq_jobs_submitted_total[{rate_range}])) by (queue)",
            ("queue",),
        ),
        TrendQuery(
            "attempt_finish_rate",
            "attempts_per_second",
            f"sum(rate(djq_job_attempts_finished_total[{rate_range}])) by (queue, outcome)",
            ("queue", "outcome"),
        ),
        TrendQuery(
            "execution_p95",
            "seconds",
            "histogram_quantile(0.95, "
            f"sum(rate(djq_job_execution_duration_seconds_bucket[{rate_range}])) "
            "by (le, queue))",
            ("queue",),
        ),
        TrendQuery(
            "queue_depth",
            "jobs",
            "sum(djq_queue_depth) by (queue)",
            ("queue",),
        ),
        TrendQuery(
            "lease_loss_rate",
            "losses_per_second",
            f"sum(rate(djq_lease_losses_total[{rate_range}])) by (operation)",
            ("operation",),
        ),
        TrendQuery(
            "recovery_rate",
            "jobs_per_second",
            f"sum(rate(djq_recovered_jobs_total[{rate_range}])) by (outcome)",
            ("outcome",),
        ),
        TrendQuery(
            "offline_workers",
            "workers",
            'sum(djq_workers{status="OFFLINE"})',
            (),
        ),
        TrendQuery(
            "state_collector_up",
            "boolean",
            "djq_state_collector_up",
            ("source",),
        ),
    )


class PrometheusQueryClient:
    """Query a configured Prometheus-compatible HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: int = 5,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        auth = (username, password) if username and password else None
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            auth=auth,
        )

    def close(self) -> None:
        self._client.close()

    def dashboard_trends(self, window: str, end: datetime) -> TrendResult:
        definition = TREND_WINDOWS[window]
        start = end - definition.duration
        queries = _queries(definition.rate_range)
        with ThreadPoolExecutor(max_workers=len(queries)) as executor:
            batches = list(
                executor.map(
                    lambda query: self._run_query(
                        query,
                        start=start,
                        end=end,
                        step_seconds=definition.step_seconds,
                    ),
                    queries,
                )
            )
        return TrendResult(
            start=start,
            end=end,
            step_seconds=definition.step_seconds,
            series=[series for batch in batches for series in batch],
        )

    def _run_query(
        self,
        query: TrendQuery,
        *,
        start: datetime,
        end: datetime,
        step_seconds: int,
    ) -> list[TrendSeries]:
        try:
            response = self._client.get(
                "/api/v1/query_range",
                params={
                    "query": query.expression,
                    "start": start.timestamp(),
                    "end": end.timestamp(),
                    "step": step_seconds,
                },
            )
            response.raise_for_status()
            body = response.json()
            if body.get("status") != "success":
                raise ValueError("query was not successful")
            results = body["data"]["result"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise PrometheusQueryError(
                f"Prometheus query failed for {query.key}"
            ) from exc
        parsed: list[TrendSeries] = []
        for result in results:
            try:
                labels = {
                    label: str(result.get("metric", {}).get(label, ""))
                    for label in query.visible_labels
                    if label in result.get("metric", {})
                }
                points = [
                    TrendPoint(
                        timestamp=datetime.fromtimestamp(float(timestamp), tz=end.tzinfo),
                        value=_finite_float(value),
                    )
                    for timestamp, value in result["values"]
                ]
            except (ValueError, TypeError, KeyError) as exc:
                raise PrometheusQueryError(
                    f"Prometheus returned invalid data for {query.key}"
                ) from exc
            parsed.append(
                TrendSeries(
                    key=query.key,
                    unit=query.unit,
                    labels=labels,
                    points=points,
                )
            )
        return parsed


def _finite_float(value: object) -> float | None:
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None

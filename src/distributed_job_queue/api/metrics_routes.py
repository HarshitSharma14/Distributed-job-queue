"""Private Prometheus scrape endpoint."""

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from distributed_job_queue.api.dependencies import require_metrics_token

router = APIRouter(tags=["operations"])


@router.get(
    "/metrics",
    include_in_schema=False,
    dependencies=[Depends(require_metrics_token)],
)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

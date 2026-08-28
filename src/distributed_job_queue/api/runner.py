"""API process entry point."""

import uvicorn

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.common.logging import configure_logging


def main() -> None:
    settings = load_settings()
    configure_logging(
        "api",
        debug=settings.debug,
        secrets=(
            settings.worker_gateway_token,
            settings.minio_access_key,
            settings.minio_secret_key,
        ),
    )
    uvicorn.run(
        "distributed_job_queue.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()

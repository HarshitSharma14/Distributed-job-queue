"""API process entry point."""

import uvicorn

from distributed_job_queue.common.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "distributed_job_queue.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()

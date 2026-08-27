"""FastAPI application factory."""

from fastapi import FastAPI

from distributed_job_queue.api.routes import router as jobs_router


def create_app() -> FastAPI:
    application = FastAPI(title="Distributed Job Queue", version="0.1.0")
    application.include_router(jobs_router)
    return application


app = create_app()

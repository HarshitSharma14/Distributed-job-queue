"""FastAPI application factory."""

from fastapi import FastAPI

from distributed_job_queue.api.errors import install_error_handlers
from distributed_job_queue.api.middleware import install_request_middleware
from distributed_job_queue.api.routes import router as jobs_router
from distributed_job_queue.api.worker_gateway_routes import router as worker_gateway_router


def create_app() -> FastAPI:
    application = FastAPI(title="Distributed Job Queue", version="0.1.0")
    install_error_handlers(application)
    install_request_middleware(application)
    application.include_router(jobs_router)
    application.include_router(worker_gateway_router)
    return application


app = create_app()

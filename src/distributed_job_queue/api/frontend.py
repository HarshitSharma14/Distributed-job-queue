"""Optional production serving for the built dashboard SPA."""

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from distributed_job_queue.common.config import load_settings


class SPAStaticFiles(StaticFiles):
    """Return the SPA entrypoint for client-side routes under `/app`."""

    async def get_response(self, path: str, scope: dict) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and "." not in Path(path).name:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and "." not in Path(path).name:
            return await super().get_response("index.html", scope)
        return response


def mount_frontend(application: FastAPI) -> None:
    """Mount a built frontend when its configured directory exists."""

    directory = Path(load_settings().frontend_dist_dir)
    if directory.is_dir() and (directory / "index.html").is_file():
        application.mount(
            "/app",
            SPAStaticFiles(directory=directory, html=True),
            name="dashboard",
        )

import asyncio

import httpx
from fastapi import FastAPI

from distributed_job_queue.api.frontend import mount_frontend


def test_frontend_mount_serves_assets_and_spa_routes(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<main>Relay dashboard</main>")
    (tmp_path / "assets" / "app.js").write_text("window.relay = true")
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(tmp_path))
    application = FastAPI()
    mount_frontend(application)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            route = await client.get("/app/admin")
            asset = await client.get("/app/assets/app.js")
            missing_asset = await client.get("/app/assets/missing.js")
            assert route.status_code == 200
            assert "Relay dashboard" in route.text
            assert asset.text == "window.relay = true"
            assert missing_asset.status_code == 404

    asyncio.run(scenario())

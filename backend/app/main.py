from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import audit, events, fusion, health, planning, plans, proposals, scenarios, sync
from app.core.config import Settings, get_settings
from app.core.db import init_db, make_engine
from app.core.errors import install_error_handlers
from app.core.hub import Hub

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    hub = Hub()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_db(engine)
        hub.bind_loop()
        yield

    app = FastAPI(
        title="AirPower API",
        description="Advisory decision-support prototype. All data is synthetic.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.hub = hub
    # Added first so CORS wraps it: its 409 replies need CORS headers too (D-72).
    sync.install_sync_middleware(app, API_PREFIX)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-AirPower-Envelope"],
    )
    install_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(scenarios.router, prefix=API_PREFIX)
    app.include_router(fusion.router, prefix=API_PREFIX)
    app.include_router(planning.router, prefix=API_PREFIX)
    app.include_router(plans.router, prefix=API_PREFIX)
    app.include_router(events.router, prefix=API_PREFIX)
    app.include_router(proposals.router, prefix=API_PREFIX)
    app.include_router(audit.router, prefix=API_PREFIX)
    app.include_router(sync.router, prefix=API_PREFIX)

    @app.websocket(f"{API_PREFIX}/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await hub.connect(ws)
        try:
            while True:
                msg = await ws.receive_json()
                if isinstance(msg, dict) and msg.get("type") == "subscribe" and msg.get(
                    "scenario_id"
                ):
                    hub.subscribe(ws, str(msg["scenario_id"]))
                    await ws.send_json({"type": "subscribed", "ts": "", "data": {
                        "scenario_id": msg["scenario_id"]}})
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(ws)

    return app


app = create_app()

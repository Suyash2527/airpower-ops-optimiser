from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(
        title="AirPower API",
        description="Advisory decision-support prototype. All data is synthetic.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix=API_PREFIX)
    return app


app = create_app()

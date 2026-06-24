"""FastAPI application factory + entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cci_api.routers import admin, agent, oauth, public, public_api, webhooks
from cci_core.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="Creator Content Intelligence",
        version="0.1.0",
        description="Search-first archive · grounded answers · Demand Radar",
    )
    # the fan-facing web app is a separate origin (Qwik) — allow it
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # public read API, no credentials
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(public.router)
    app.include_router(oauth.router)
    app.include_router(webhooks.router)
    app.include_router(admin.router)
    app.include_router(agent.router)
    app.include_router(public_api.router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"ok": True}

    return app


app = create_app()


def run() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    s = get_settings()
    uvicorn.run("cci_api.main:app", host=s.api_host, port=s.api_port)


if __name__ == "__main__":
    run()

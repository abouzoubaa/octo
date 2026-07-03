"""FastAPI application factory + entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from cci_api.observability import (
    RequestContextMiddleware,
    configure_logging,
    init_sentry,
    render_metrics,
)
from cci_api.routers import admin, agent, billing, oauth, public, public_api, webhooks
from cci_core.config import get_settings


def create_app() -> FastAPI:
    configure_logging()
    init_sentry()
    # fail closed in production: refuse to boot with insecure-default secrets
    settings = get_settings()
    if not settings.debug:
        problems = settings.assert_production_secrets()
        if problems:
            raise RuntimeError(
                "Refusing to start with insecure production config: " + "; ".join(problems))
    app = FastAPI(
        title="Creator Content Intelligence",
        version="0.1.0",
        description="Search-first archive · grounded answers · Demand Radar",
    )
    app.add_middleware(RequestContextMiddleware)
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
    app.include_router(billing.router)
    app.include_router(billing.admin_router)
    app.include_router(public_api.router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/metrics", tags=["ops"], response_class=PlainTextResponse)
    def metrics() -> str:
        return render_metrics()

    return app


app = create_app()


def run() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("cci_api.main:app", host=s.api_host, port=s.api_port)


if __name__ == "__main__":
    run()

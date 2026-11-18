import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from app.config import settings
from app.error_handlers import register_error_handlers
from app.logging_conf import configure_logging
from app.middleware.body_limit import BodyLimitMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import (
    arena,
    auth,
    contracts,
    health,
    org_paypal,
    playground,
    policy,
    receipts,
    reconcile,
    stats,
    stream,
    system,
    webhooks,
    workers,
)
from app.services.scheduler import scheduler

# Initialize structured logging
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema migrations run exclusively through Alembic; the application never calls create_all
    if settings.PAYLAP_JOBS_ENABLED:
        scheduler.start()
    yield
    if settings.PAYLAP_JOBS_ENABLED:
        await scheduler.stop()


app = FastAPI(
    title="PayLap Settlement API",
    description="Multi-tenant settlement API for verified-delivery payment holds.",
    version="1.0.0",
    docs_url="/docs" if settings.PAYLAP_ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.PAYLAP_ENABLE_DOCS else None,
    lifespan=lifespan,
)

# Register custom error handlers (Standard error body format)
register_error_handlers(app)

# Middlewares are executed in reverse order of addition:
# 1. RequestIdMiddleware (runs first and sets request.state.request_id)
# 2. SecurityHeadersMiddleware (attaches standard security headers)
# 3. BodyLimitMiddleware (enforces 5MB max payload size)
# 4. RateLimitMiddleware (token-bucket limiter)
# 5. CORSMiddleware (strictly restricted to PAYLAP_CORS_ORIGINS, never *)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.PAYLAP_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Health & Probe routes (/healthz, /readyz)
app.include_router(health.router)

# V1 API Routes
app.include_router(auth.router)
app.include_router(org_paypal.router)
app.include_router(policy.router)
app.include_router(contracts.router)
app.include_router(receipts.router)
app.include_router(webhooks.router)
app.include_router(reconcile.router)
app.include_router(stats.router)
app.include_router(workers.router)
app.include_router(playground.router)
app.include_router(arena.router)
app.include_router(stream.router)
app.include_router(system.router)


# Frontend SPA Static Assets and Catch-all Routing
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
frontend_assets = os.path.join(frontend_dist, "assets")

if os.path.exists(frontend_assets):
    app.mount("/assets", StaticFiles(directory=frontend_assets), name="static_assets")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_spa(full_path: str):
    """
    Serve compiled React SPA for client-side routes, falling back to index.html.
    Preserves 404 for API, health, and documentation prefixes.
    """
    clean_path = full_path.lstrip("/")
    if (
        clean_path.startswith("v1")
        or clean_path.startswith("docs")
        or clean_path.startswith("openapi.json")
        or clean_path in ("healthz", "readyz")
    ):
        raise HTTPException(status_code=404, detail="Endpoint not found")

    dist_index = os.path.join(frontend_dist, "index.html")
    if os.path.exists(dist_index):
        return FileResponse(dist_index)
    return {"message": "PayLap Settlement API is running. Production frontend not built."}

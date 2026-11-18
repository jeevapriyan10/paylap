import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.config import settings
from app.error_handlers import register_error_handlers
from app.logging_conf import configure_logging
from app.middleware.body_limit import BodyLimitMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import arena, auth, contracts, health, org_paypal, policy, receipts, stream, system, workers

# Initialize structured logging
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema migrations run exclusively through Alembic; the application never calls create_all
    yield


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
app.include_router(workers.router)
app.include_router(arena.router)
app.include_router(stream.router)
app.include_router(system.router)


@app.get("/", include_in_schema=False)
def serve_frontend_placeholder():
    index_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "PayLap Settlement API is running. See /docs for API documentation."}

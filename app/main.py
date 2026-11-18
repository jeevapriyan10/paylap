import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.config import settings
from app.routers import arena, auth, contracts, stream, system, workers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # App never calls create_all; schema is managed exclusively via Alembic
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

# Strict CORS configuration restricted to settings.PAYLAP_CORS_ORIGINS (never *)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.PAYLAP_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth.router)
app.include_router(system.router)
app.include_router(contracts.router)
app.include_router(workers.router)
app.include_router(arena.router)
app.include_router(stream.router)


@app.get("/", include_in_schema=False)
def serve_frontend_placeholder():
    index_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "PayLap Settlement API is running. See /docs for API documentation."}

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.config import settings
from app.db import init_db
from app.routers import contracts, system, workers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    init_db()
    yield


app = FastAPI(
    title="PayLap API",
    description="Escrow and milestone-settlement layer for AI agents ('Pay on proof, not on promise').",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS middleware for localhost development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(system.router)
app.include_router(contracts.router)
app.include_router(workers.router)


@app.get("/", include_in_schema=False)
def serve_frontend_placeholder():
    """Serve the minimal frontend static placeholder page."""
    index_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "PayLap API is running. See /docs for API documentation."}

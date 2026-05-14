from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from rag_benchmarking.api.routes import (
    datasets,
    documents,
    evaluations,
    health,
    ingestions,
    jobs,
    query,
)
from rag_benchmarking.core.config import get_settings
from rag_benchmarking.core.logging import configure_logging

configure_logging()

settings = get_settings()

app = FastAPI(
    title="SEC Filings Agentic RAG API",
    version="0.1.0",
    description="FastAPI backend for SEC filing ingestion, retrieval, traces, and evaluations.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(datasets.router)
app.include_router(documents.router)
app.include_router(ingestions.router)
app.include_router(jobs.router)
app.include_router(query.router)
app.include_router(evaluations.router)


frontend_path = Path(settings.frontend_dist_path)
if frontend_path.exists():
    assets_path = frontend_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        requested = frontend_path / full_path
        if requested.exists() and requested.is_file():
            return FileResponse(requested)
        return FileResponse(frontend_path / "index.html")

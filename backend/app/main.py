# -*- coding: utf-8 -*-
"""
app/main.py

FastAPI application entry point.

Startup sequence:
  1. Load settings from .env
  2. Initialise Cognee (Cloud or local, depending on env vars)
  3. Register all routes

CORS is set permissively for development — tighten ALLOWED_ORIGINS in .env
before any production deployment.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.endpoints import router
from app.core.cognee_setup import init_cognee, teardown_cognee
from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="PaperMind API",
        description=(
            "Graph-based research paper comprehension assistant. "
            "Powered by Cognee knowledge graphs and OpenRouter LLMs."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow the Vite/Next.js dev server and production frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Cognee lifecycle
    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("PaperMind backend starting up...")
        await init_cognee()
        logger.info("Cognee initialised. Ready to process papers.")
        
        # Clean up stuck jobs
        from app.services.job_store import get_stuck_jobs, fail_job
        try:
            stuck_jobs = await get_stuck_jobs()
            for job in stuck_jobs:
                logger.info("Marking stuck job %s as failed due to server restart", job["id"])
                await fail_job(job["id"], job.get("stage", "unknown"), "Server interrupted. Please upload the paper again.")
        except Exception as exc:
            logger.error("Failed to clean up stuck jobs: %s", exc)

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        await teardown_cognee()
        logger.info("PaperMind backend shut down cleanly.")

    # Register all API routes under /api/v1
    app.include_router(router, prefix="/api/v1")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )

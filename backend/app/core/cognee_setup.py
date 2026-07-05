# -*- coding: utf-8 -*-
"""
app/core/cognee_setup.py

Initialises the Cognee connection at application startup.

HOW COGNEE CLOUD WORKS (from docs.cognee.ai/python-api/serve):
  cognee.serve(url=..., api_key=...) routes all subsequent Cognee SDK
  operations (remember, recall, forget, improve) to your Cloud tenant.
  Cognee Cloud runs its own LLM and embedding pipeline server-side.
  You do NOT need to provide LLM or embedding API keys for Cognee Cloud.

TWO VARIABLES IS ALL YOU NEED FOR CLOUD MODE:
  COGNEE_SERVICE_URL - your tenant API Base URL from the dashboard
  COGNEE_API_KEY     - your X-Api-Key from the dashboard

LOCAL MODE (fallback, no Cognee account needed):
  When COGNEE_SERVICE_URL is empty, Cognee uses SQLite+LanceDB+Kuzu locally.
  In that case we configure the LLM and embedding providers from the env
  so Cognee's internal cognify() pipeline has a working LLM.

  set_llm_config() and set_embedding_config() keys must match the internal
  attribute names exactly (discovered from docs.cognee.ai/python-api/config):
    llm_provider, llm_model, llm_api_key, llm_endpoint
    embedding_provider, embedding_model, embedding_api_key, embedding_endpoint

Switching between Cloud and local mode is a single .env change.
"""

import logging
import os

import cognee

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def init_cognee() -> None:
    """
    Called once at FastAPI startup.
    Routes to Cognee Cloud if credentials are present, otherwise stays local.
    """
    os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] = "true"

    settings = get_settings()

    if settings.cognee_cloud_enabled:
        # Cloud mode
        # cognee.serve() reads COGNEE_SERVICE_URL and COGNEE_API_KEY from env
        # automatically, but we pass them explicitly so the connection origin
        # is visible in startup logs rather than being implicit.
        logger.info("Connecting to Cognee Cloud -> %s", settings.cognee_service_url)
        try:
            await cognee.serve(
                url=settings.cognee_service_url,
                api_key=settings.cognee_api_key,
            )
            logger.info("Cognee Cloud connection established.")
        except Exception as exc:
            # A startup connection failure is logged but not fatal - the app
            # still starts and will fail gracefully at the first Cognee call.
            logger.error(
                "Cognee Cloud connection failed: %s. "
                "All graph operations will fail until this is resolved.",
                exc,
            )
    else:
        # Local mode
        # Cognee runs entirely in-process using SQLite + LanceDB + Kuzu.
        # Ensure we write data to a persistent project directory, not the virtual environment!
        data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data/.cognee_system"))
        os.makedirs(data_dir, exist_ok=True)
        cognee.config.data_root_directory = data_dir
        
        logger.info("Cognee running in local mode (SQLite + LanceDB + Kuzu)")
        logger.info("Cognee data directory set to: %s", data_dir)

        if settings.llm_api_key:
            cognee.config.set_llm_config({
                "llm_provider": settings.llm_provider,
                "llm_model": settings.llm_model,
                "llm_api_key": settings.llm_api_key,
                "llm_endpoint": settings.llm_endpoint,
            })

        if settings.embedding_api_key:
            cognee.config.set_embedding_config({
                "embedding_provider": settings.embedding_provider,
                "embedding_model": settings.embedding_model,
                "embedding_api_key": settings.embedding_api_key,
                "embedding_endpoint": settings.embedding_endpoint,
            })


async def teardown_cognee() -> None:
    """Called at FastAPI shutdown - disconnect from Cloud if connected."""
    settings = get_settings()
    if settings.cognee_cloud_enabled:
        try:
            await cognee.disconnect()
            logger.info("Cognee Cloud disconnected cleanly.")
        except Exception as exc:
            logger.debug("cognee.disconnect() raised: %s", exc)
    logger.info("Cognee teardown complete.")

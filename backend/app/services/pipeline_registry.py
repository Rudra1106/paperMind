# -*- coding: utf-8 -*-
"""
app/services/pipeline_registry.py

Postgres-backed execution step registry for DAG pipeline tracking.
Provides observability, resumability, and state management for background ingestion.
"""

import logging
from datetime import datetime
from app.core.supabase_client import get_supabase

logger = logging.getLogger(__name__)

async def get_step(paper_id: str, step_name: str) -> dict | None:
    """Retrieve a step's details from database."""
    try:
        supabase = get_supabase()
        response = supabase.table("pipeline_steps")\
            .select("*")\
            .eq("paper_id", paper_id)\
            .eq("step_name", step_name)\
            .execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
    except Exception as exc:
        logger.error("Failed to get pipeline step %s for paper %s: %s", step_name, paper_id, exc)
    return None

async def clear_steps(paper_id: str) -> None:
    """Clear all pipeline steps for a paper to force a fresh run if DB is corrupted."""
    try:
        supabase = get_supabase()
        supabase.table("pipeline_steps").delete().eq("paper_id", paper_id).execute()
    except Exception as exc:
        logger.error("Failed to clear pipeline steps for paper %s: %s", paper_id, exc)

async def mark_step_running(paper_id: str, step_name: str) -> None:
    """Upsert the step status to 'running' with start timestamp."""
    try:
        supabase = get_supabase()
        supabase.table("pipeline_steps").upsert({
            "paper_id": paper_id,
            "step_name": step_name,
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
            "error": None
        }, on_conflict="paper_id,step_name").execute()
    except Exception as exc:
        logger.error("Failed to mark step %s as running: %s", step_name, exc)

async def mark_step_done(paper_id: str, step_name: str, result: dict) -> None:
    """Upsert step status to 'done' with result and finish timestamp."""
    try:
        supabase = get_supabase()
        supabase.table("pipeline_steps").upsert({
            "paper_id": paper_id,
            "step_name": step_name,
            "status": "done",
            "result": result,
            "finished_at": datetime.utcnow().isoformat(),
            "error": None
        }, on_conflict="paper_id,step_name").execute()
    except Exception as exc:
        logger.error("Failed to mark step %s as done: %s", step_name, exc)

async def mark_step_failed(paper_id: str, step_name: str, error: str) -> None:
    """Upsert step status to 'failed' with error info."""
    try:
        supabase = get_supabase()
        supabase.table("pipeline_steps").upsert({
            "paper_id": paper_id,
            "step_name": step_name,
            "status": "failed",
            "finished_at": datetime.utcnow().isoformat(),
            "error": error
        }, on_conflict="paper_id,step_name").execute()
    except Exception as exc:
        logger.error("Failed to mark step %s as failed: %s", step_name, exc)

async def get_or_run_step(paper_id: str, step_name: str, fn, *args, **kwargs):
    """
    If the step is already marked 'done', returns the cached result.
    Otherwise, executes the async function, marks it 'done', and returns the result.
    In case of error, marks it 'failed' and raises the exception.
    """
    step = await get_step(paper_id, step_name)
    if step and step.get("status") == "done":
        logger.info("Resuming pipeline: Step '%s' already completed. Using cached result.", step_name)
        return step.get("result")

    await mark_step_running(paper_id, step_name)
    try:
        if asyncio_is_coroutine_function(fn):
            result = await fn(*args, **kwargs)
        else:
            result = fn(*args, **kwargs)
        await mark_step_done(paper_id, step_name, result)
        return result
    except Exception as exc:
        await mark_step_failed(paper_id, step_name, str(exc))
        logger.error("Step '%s' failed for paper '%s': %s", step_name, paper_id, exc, exc_info=True)
        raise exc

def asyncio_is_coroutine_function(fn) -> bool:
    import inspect
    return inspect.iscoroutinefunction(fn)

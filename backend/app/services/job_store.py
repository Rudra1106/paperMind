# -*- coding: utf-8 -*-
import logging
from app.core.supabase_client import get_supabase

logger = logging.getLogger(__name__)

async def create_job(job_id: str, user_id: str, pdf_hash: str) -> None:
    """Create a new job record."""
    supabase = get_supabase()
    supabase.table("jobs").insert({
        "id": job_id,
        "user_id": user_id,
        "pdf_hash": pdf_hash,
        "status": "processing",
        "stage": "queued"
    }).execute()

async def set_stage(job_id: str, stage: str) -> None:
    """Update the current stage of a job."""
    logger.info("[job %s] stage: %s", job_id, stage)
    supabase = get_supabase()
    supabase.table("jobs").update({
        "stage": stage
    }).eq("id", job_id).execute()

async def complete_job(job_id: str, paper_id: str) -> None:
    """Mark a job as successfully completed."""
    supabase = get_supabase()
    supabase.table("jobs").update({
        "status": "done",
        "stage": "complete",
        "paper_id": paper_id
    }).eq("id", job_id).execute()

async def fail_job(job_id: str, stage: str, error: str) -> None:
    """Mark a job as failed with an error message."""
    supabase = get_supabase()
    supabase.table("jobs").update({
        "status": "error",
        "stage": stage,
        "error": error
    }).eq("id", job_id).execute()

async def get_job(job_id: str) -> dict | None:
    """Retrieve a job by ID (RLS ensures user can only see their own jobs if user JWT is used)."""
    supabase = get_supabase()
    response = supabase.table("jobs").select("*").eq("id", job_id).execute()
    return response.data[0] if response.data else None

async def get_stuck_jobs() -> list[dict]:
    """Retrieve all jobs that are stuck in 'processing' status."""
    supabase = get_supabase()
    response = supabase.table("jobs").select("*").eq("status", "processing").execute()
    return response.data or []

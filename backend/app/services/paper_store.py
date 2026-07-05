# -*- coding: utf-8 -*-
import logging
from app.core.supabase_client import get_supabase

logger = logging.getLogger(__name__)

async def get_paper_by_hash(pdf_hash: str) -> dict | None:
    """Check if a paper has already been processed and cached."""
    supabase = get_supabase()
    response = supabase.table("papers").select("*").eq("pdf_hash", pdf_hash).execute()
    return response.data[0] if response.data else None

async def save_paper(
    paper_id: str,
    pdf_hash: str,
    title: str,
    filename: str,
    concepts: list,
    edges: dict,
    storage_path: str,
    arxiv_id: str | None = None,
) -> None:
    """Persist processed paper results so re-uploads are instant."""
    supabase = get_supabase()
    supabase.table("papers").insert({
        "id": paper_id,
        "pdf_hash": pdf_hash,
        "title": title,
        "filename": filename,
        "concepts": concepts,
        "edges": edges,
        "storage_path": storage_path,
        "arxiv_id": arxiv_id,
    }).execute()

async def get_paper_by_id(paper_id: str) -> dict | None:
    """Retrieve paper details by its ID."""
    supabase = get_supabase()
    response = supabase.table("papers").select("*").eq("id", paper_id).execute()
    return response.data[0] if response.data else None

async def upload_pdf_to_storage(user_id: str, pdf_bytes: bytes, pdf_hash: str) -> str:
    """Uploads PDF to Supabase storage and returns the storage path."""
    supabase = get_supabase()
    path_on_storage = f"{user_id}/{pdf_hash}.pdf"
    
    # Try to upload, ignore if already exists (another user uploaded same paper)
    try:
        supabase.storage.from_("papers").upload(
            path=path_on_storage,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf"}
        )
    except Exception as exc:
        logger.debug("Storage upload skipped or failed (might already exist): %s", exc)
        
    return path_on_storage


async def get_paper_pdf_url(paper_id: str) -> str:
    """Retrieve the paper and return a signed URL to read the PDF."""
    paper = await get_paper_by_id(paper_id)
    if not paper:
        return ""
    storage_path = paper.get("storage_path")
    if not storage_path:
        return ""

    supabase = get_supabase()
    try:
        # Generate a signed URL valid for 2 hours (7200 seconds)
        res = supabase.storage.from_("papers").create_signed_url(storage_path, expires_in=7200)
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl") or ""
        return str(res)
    except Exception as exc:
        logger.error("Failed to create signed URL for paper %s: %s", paper_id, exc)
        # Fallback to public url
        try:
            return supabase.storage.from_("papers").get_public_url(storage_path)
        except Exception:
            return ""


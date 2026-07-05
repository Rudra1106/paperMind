# -*- coding: utf-8 -*-
"""
app/services/citation_registry.py

Citation registry service to manage inline citations.
Ties Wikipedia definitions, Semantic Scholar references, OpenAlex works,
and Primary Sources to sequential numbered indices.
"""

import logging
from app.core.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# In-memory fallback database to prevent server crash if database migration is missing
_in_memory_registry = {}  # key: (paper_id, session_id), value: list of dicts

async def register_citation(
    paper_id: str,
    session_id: str | None,
    source_type: str,
    title: str,
    authors: list[str] = None,
    year: int = None,
    venue: str = None,
    url: str = None,
    is_preprint: bool = False,
    influence_score: float = 0.0,
) -> int:
    """
    Registers a citation source for a paper/session context.
    Returns a sequential 1-based integer index.
    If the citation already exists in this context, returns its current index.
    """
    authors = authors or []
    url = url or ""
    title = title.strip()
    session_id_str = str(session_id) if session_id else None

    # Step 1: Attempt database lookup/creation
    try:
        supabase = get_supabase()
        
        # Check if already exists in DB
        query = supabase.table("citations").select("citation_index").eq("paper_id", paper_id)
        if session_id_str:
            query = query.eq("session_id", session_id_str)
        else:
            query = query.is_("session_id", "null")

        if url:
            query = query.eq("url", url)
        else:
            query = query.ilike("title", title)

        res = query.execute()
        if res.data:
            return res.data[0]["citation_index"]

        # Find max citation_index in DB
        max_query = supabase.table("citations").select("citation_index").eq("paper_id", paper_id)
        if session_id_str:
            max_query = max_query.eq("session_id", session_id_str)
        else:
            max_query = max_query.is_("session_id", "null")
        
        max_res = max_query.order("citation_index", desc=True).limit(1).execute()
        
        next_index = 1
        if max_res.data:
            next_index = max_res.data[0]["citation_index"] + 1

        # Insert new citation in DB
        supabase.table("citations").insert({
            "paper_id": paper_id,
            "session_id": session_id_str,
            "citation_index": next_index,
            "source_type": source_type,
            "title": title,
            "authors": authors,
            "year": year,
            "venue": venue,
            "url": url,
            "is_preprint": is_preprint,
            "influence_score": influence_score
        }).execute()

        logger.info(
            "Registered citation index %d in DB for paper %s / session %s: %s",
            next_index, paper_id, session_id_str, title[:40]
        )
        return next_index

    except Exception as exc:
        logger.warning(
            "Failed database registration for citation (falling back to memory): %s", exc
        )
        # Fallback to in-memory store
        ctx_key = (paper_id, session_id_str)
        if ctx_key not in _in_memory_registry:
            _in_memory_registry[ctx_key] = []
        
        registry_list = _in_memory_registry[ctx_key]
        
        # Check if already exists in memory
        for item in registry_list:
            if (url and item["url"] == url) or (not url and item["title"].lower() == title.lower()):
                return item["citation_index"]
        
        next_index = len(registry_list) + 1
        new_item = {
            "citation_index": next_index,
            "source_type": source_type,
            "title": title,
            "authors": authors,
            "year": year,
            "venue": venue,
            "url": url,
            "is_preprint": is_preprint,
            "influence_score": influence_score
        }
        registry_list.append(new_item)
        logger.info(
            "Registered citation index %d in MEMORY: %s",
            next_index, title[:40]
        )
        return next_index

async def get_citations(paper_id: str, session_id: str | None = None) -> list[dict]:
    """
    Get all citations for a given paper, combined with any session-specific citations.
    Returns a sorted list of citations.
    """
    session_id_str = str(session_id) if session_id else None
    results = []

    # Try DB
    try:
        supabase = get_supabase()
        
        # Fetch paper-wide citations (session_id = null)
        paper_res = supabase.table("citations")\
            .select("*")\
            .eq("paper_id", paper_id)\
            .is_("session_id", "null")\
            .order("citation_index", desc=False)\
            .execute()
        if paper_res.data:
            results.extend(paper_res.data)

        # Fetch session-specific citations
        if session_id_str:
            sess_res = supabase.table("citations")\
                .select("*")\
                .eq("paper_id", paper_id)\
                .eq("session_id", session_id_str)\
                .order("citation_index", desc=False)\
                .execute()
            if sess_res.data:
                results.extend(sess_res.data)

    except Exception as exc:
        logger.warning("Failed database fetch for citations (falling back to memory): %s", exc)
        
        # Read from in-memory fallback
        # Fetch paper-wide citations
        paper_list = _in_memory_registry.get((paper_id, None), [])
        results.extend(paper_list)
        
        # Fetch session-specific citations
        if session_id_str:
            sess_list = _in_memory_registry.get((paper_id, session_id_str), [])
            results.extend(sess_list)

    # Sort combined results by index
    results.sort(key=lambda x: x.get("citation_index") or 0)
    
    # Standardise list formatting
    formatted = []
    for item in results:
        formatted.append({
            "id": item.get("citation_index") or item.get("id"),
            "citation_index": item.get("citation_index"),
            "source_type": item.get("source_type"),
            "title": item.get("title"),
            "authors": item.get("authors") or [],
            "year": item.get("year"),
            "venue": item.get("venue"),
            "url": item.get("url"),
            "is_preprint": item.get("is_preprint", False),
            "influence_score": item.get("influence_score") or 0.0
        })
    return formatted

# -*- coding: utf-8 -*-
"""
app/services/external_cache.py

Shared Postgres-backed caching layer for external API requests
(Wikipedia, Semantic Scholar, Wolfram).
Ties back to shared knowledge principle to prevent duplicate external hits.

CACHE_VERSION: Bump this to invalidate ALL cached entries globally.
- v2 → v3: Invalidates stale Wikipedia definitions (e.g. wrong "transformer"
  entry that resolved to electrical engineering instead of ML).
"""

import logging
from datetime import datetime, timedelta
from app.core.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Bump this constant to globally invalidate all cached external API responses.
# All cache keys are prefixed with this version string.
CACHE_VERSION = "v3"


async def get_cached(key: str) -> dict | None:
    """Retrieve cached payload if present and not expired."""
    try:
        supabase = get_supabase()
        response = supabase.table("external_cache")\
            .select("*")\
            .eq("cache_key", key)\
            .execute()
        if response.data and len(response.data) > 0:
            row = response.data[0]
            expires_at_str = row.get("expires_at")
            if expires_at_str:
                expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                # If current time is past expiry, ignore/delete it
                if datetime.now(expires_at.tzinfo) > expires_at:
                    logger.debug("Cache expired for key: %s", key)
                    # Non-blocking deletion
                    supabase.table("external_cache").delete().eq("cache_key", key).execute()
                    return None
            return row.get("payload")
    except Exception as exc:
        logger.error("Failed to read external cache for key %s: %s", key, exc)
    return None

async def set_cached(key: str, source: str, payload: dict, ttl_seconds: int = None) -> None:
    """Cache the response payload with an optional TTL."""
    try:
        supabase = get_supabase()
        expires_at = None
        if ttl_seconds is not None:
            expires_at = (datetime.utcnow() + timedelta(seconds=ttl_seconds)).isoformat() + "Z"
        
        supabase.table("external_cache").upsert({
            "cache_key": key,
            "source": source,
            "payload": payload,
            "expires_at": expires_at,
            "fetched_at": datetime.utcnow().isoformat() + "Z"
        }, on_conflict="cache_key").execute()
    except Exception as exc:
        logger.error("Failed to write external cache for key %s: %s", key, exc)

async def invalidate_concept_cache(concept_name: str) -> int:
    """
    Delete all external cache entries for a specific concept name.
    Matches keys containing the concept canonical name across all sources
    (wikipedia, wolfram, semantic_scholar).
    Returns the number of rows deleted.
    """
    from app.utils.canonical import canonical
    canon = canonical(concept_name)
    deleted = 0
    try:
        supabase = get_supabase()
        # Fetch matching keys first (Supabase Python client doesn't support LIKE delete directly)
        response = supabase.table("external_cache")\
            .select("cache_key")\
            .ilike("cache_key", f"%:{canon}%")\
            .execute()
        if response.data:
            keys = [row["cache_key"] for row in response.data]
            for key in keys:
                supabase.table("external_cache").delete().eq("cache_key", key).execute()
                deleted += 1
            logger.info("Invalidated %d cache entries for concept '%s'", deleted, concept_name)
    except Exception as exc:
        logger.error("Failed to invalidate cache for concept %s: %s", concept_name, exc)
    return deleted


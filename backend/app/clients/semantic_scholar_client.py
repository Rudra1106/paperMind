# -*- coding: utf-8 -*-
"""
app/clients/semantic_scholar_client.py

Semantic Scholar Graph API client with shared Postgres caching.
Fetches abstracts, citation counts, references, citations, and papers for topic mapping.
"""

import asyncio
import logging
import httpx
from aiolimiter import AsyncLimiter
from app.services.external_cache import get_cached, set_cached, CACHE_VERSION

logger = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1"

# Rate limiting lock to enforce max 1 request per 3.1 seconds unauthenticated
_limiter = AsyncLimiter(1, 3.1)

async def _rate_limited_request(client: httpx.AsyncClient, method: str, path: str, params: dict = None) -> dict | None:
    """Enforce rate limits and execute HTTP request using AsyncLimiter."""
    url = f"{BASE_URL}{path}"
    
    async with _limiter:
        for attempt in range(4):
            try:
                if attempt == 0:
                    logger.info("Semantic Scholar request: %s with params %s", url, params)
                response = await client.request(method, url, params=params, timeout=15.0)
                
                if response.status_code == 429:
                    wait_time = 5.0 * (2 ** attempt)  # 5s, 10s, 20s
                    if attempt < 3:
                        logger.warning("Semantic Scholar rate limited (429). Retrying after %ss (attempt %d)...", wait_time, attempt + 1)
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error("Semantic Scholar rate limited (429) after max retries.")
                        return None
                
                if response.status_code == 404:
                    return None
                    
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                logger.error("Semantic Scholar request failed on attempt %d: %s", attempt + 1, exc)
                if attempt < 3:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                return None

async def get_paper_by_arxiv_id(arxiv_id: str) -> dict | None:
    """Fetch paper details from arXiv ID. Cached for 7 days."""
    key = f"{CACHE_VERSION}:scholar:paper:{arxiv_id}"
    cached = await get_cached(key)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        # Request references and TLDR
        fields = "paperId,title,abstract,year,authors,citationCount,referenceCount,externalIds,tldr,references"
        data = await _rate_limited_request(client, "GET", f"/paper/arXiv:{arxiv_id}", params={"fields": fields})
        if data:
            await set_cached(key, "semantic_scholar", data, ttl_seconds=7*86400)
        return data

async def search_concept(concept_name: str) -> dict | None:
    """Search for a concept to fetch reference papers. Cached for 7 days."""
    key = f"{CACHE_VERSION}:scholar:search:{canonical_search_key(concept_name)}"
    cached = await get_cached(key)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        fields = "paperId,title,abstract,tldr,citationCount"
        data = await _rate_limited_request(client, "GET", "/paper/search", params={
            "query": concept_name,
            "fields": fields,
            "limit": 5
        })
        if data:
            await set_cached(key, "semantic_scholar", data, ttl_seconds=7*86400)
        return data

async def get_citations(paper_id: str) -> dict | None:
    """Fetch citing papers for a given Semantic Scholar paperId."""
    key = f"{CACHE_VERSION}:scholar:citations:{paper_id}"
    cached = await get_cached(key)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        fields = "citations.paperId,citations.title,citations.year,citations.externalIds"
        data = await _rate_limited_request(client, "GET", f"/paper/{paper_id}", params={"fields": fields})
        if data:
            await set_cached(key, "semantic_scholar", data, ttl_seconds=7*86400)
        return data


async def fetch_paper_references(arxiv_id: str) -> dict:
    """
    Fetch the full reference list (papers this paper cites) and the inbound
    citation list (papers that cite this one) from Semantic Scholar.

    Uses the paper's arXiv ID for lookup. Semantic Scholar resolves arXiv IDs
    directly via the /paper/arXiv:{id} endpoint.

    Returns:
        {
          "references": [
            {"title": str, "year": int, "authors": [...], "semantic_scholar_url": str}
          ],
          "citations": [
            {"title": str, "year": int, "semantic_scholar_url": str}
          ],
          "paper_id": str | None,   # Semantic Scholar internal paperId
        }
    """
    key = f"{CACHE_VERSION}:scholar:refs:{arxiv_id}"
    cached = await get_cached(key)
    if cached:
        return cached

    fields = (
        "paperId,"
        "references.paperId,references.title,references.year,references.authors,references.externalIds,"
        "citations.paperId,citations.title,citations.year,citations.authors,citations.externalIds"
    )

    result = {"references": [], "citations": [], "paper_id": None}

    async with httpx.AsyncClient() as client:
        data = await _rate_limited_request(
            client, "GET",
            f"/paper/arXiv:{arxiv_id}",
            params={"fields": fields},
        )

    if not data:
        logger.warning("Semantic Scholar returned no data for arXiv ID: %s", arxiv_id)
        return result

    result["paper_id"] = data.get("paperId")

    def _build_ss_url(paper: dict) -> str:
        pid = paper.get("paperId", "")
        return f"https://www.semanticscholar.org/paper/{pid}" if pid else ""

    def _format_authors(paper: dict) -> list[str]:
        return [a.get("name", "") for a in (paper.get("authors") or [])[:3]]

    for ref in (data.get("references") or []):
        if ref.get("title"):
            result["references"].append({
                "title": ref["title"],
                "year": ref.get("year"),
                "authors": _format_authors(ref),
                "semantic_scholar_url": _build_ss_url(ref),
            })

    for cit in (data.get("citations") or []):
        if cit.get("title"):
            result["citations"].append({
                "title": cit["title"],
                "year": cit.get("year"),
                "authors": _format_authors(cit),
                "semantic_scholar_url": _build_ss_url(cit),
            })

    # Sort references chronologically (oldest first — lineage trace)
    result["references"].sort(key=lambda r: r.get("year") or 0)
    # Sort citations reverse-chronologically (most recent first)
    result["citations"].sort(key=lambda c: c.get("year") or 0, reverse=True)

    await set_cached(key, "semantic_scholar", result, ttl_seconds=7 * 86400)
    return result


def canonical_search_key(name: str) -> str:
    from app.utils.canonical import canonical
    return canonical(name)

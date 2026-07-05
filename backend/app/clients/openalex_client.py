# -*- coding: utf-8 -*-
"""
app/clients/openalex_client.py

OpenAlex API client with shared Postgres caching.
Fetches high-quality metadata, peer-review/preprint status, and citation percentile (influence score) for papers.
"""

import urllib.parse
import logging
import httpx
from app.services.external_cache import get_cached, set_cached, CACHE_VERSION

logger = logging.getLogger(__name__)

# Etiquette guidelines: use polite pool by appending a contact email
MAILTO = "bot@papermind.app"
BASE_URL = "https://api.openalex.org"

async def fetch_work_by_title_or_doi(query: str) -> dict | None:
    """
    Search OpenAlex works for a given query (title, concept name, or DOI).
    Cached for 7 days.
    """
    if not query or len(query.strip()) < 3:
        return None

    # Normalise query for cache key
    sanitized_query = query.strip().lower()
    # Replace slashes and spaces for clean cache key
    cache_safe_query = urllib.parse.quote_plus(sanitized_query)[:150]
    cache_key = f"{CACHE_VERSION}:openalex:work:{cache_safe_query}"

    cached = await get_cached(cache_key)
    if cached is not None:
        return cached

    params = {
        "mailto": MAILTO
    }

    # Detect if query looks like a DOI
    # e.g., 10.1109/5.771073 or https://doi.org/...
    is_doi = False
    doi_clean = None
    if "10." in query:
        # Extract DOI portion
        import re
        match = re.search(r'(10\.\d{4,9}/[-._;()/:A-Z0-9]+)', query, re.IGNORECASE)
        if match:
            is_doi = True
            doi_clean = match.group(1)

    async with httpx.AsyncClient() as client:
        try:
            if is_doi:
                url = f"{BASE_URL}/works/https://doi.org/{doi_clean}"
                logger.info("OpenAlex fetching DOI directly: %s", url)
                response = await client.get(url, params=params, timeout=10.0)
            else:
                url = f"{BASE_URL}/works"
                params["search"] = query
                params["per_page"] = 1
                logger.info("OpenAlex searching works: %s with query '%s'", url, query)
                response = await client.get(url, params=params, timeout=10.0)

            if response.status_code == 404:
                await set_cached(cache_key, "openalex", {}, ttl_seconds=7*86400)
                return {}

            response.raise_for_status()
            data = response.json()

            # Format the output work object
            work = None
            if is_doi:
                work = data
            else:
                results = data.get("results", [])
                if results:
                    work = results[0]

            if not work:
                await set_cached(cache_key, "openalex", {}, ttl_seconds=7*86400)
                return {}

            # Parse details safely
            title = work.get("title") or ""
            
            # Format authors: limit to first 3
            authors = []
            for authorship in work.get("authorships", [])[:3]:
                author_node = authorship.get("author", {})
                if author_node.get("display_name"):
                    authors.append(author_node["display_name"])

            year = work.get("publication_year")

            primary_loc = work.get("primary_location") or {}
            source = primary_loc.get("source") or {}
            venue = source.get("display_name") or ""
            
            # Determine preprint vs peer-reviewed
            # Standard preprints reside in repositories (e.g. arXiv, bioRxiv)
            source_type = source.get("type") or ""
            is_preprint = (source_type == "repository" or "arxiv" in venue.lower())
            
            # Extract influence score (cited_by_percentile_year)
            percentile_node = work.get("cited_by_percentile_year") or {}
            # Can be float, dict, or missing. Often it's a dict like {"min": 92.5, "max": 95}
            influence_score = 0.0
            if isinstance(percentile_node, dict):
                influence_score = percentile_node.get("min") or percentile_node.get("value") or 0.0
            elif isinstance(percentile_node, (int, float)):
                influence_score = float(percentile_node)

            url = work.get("doi") or primary_loc.get("landing_page_url") or ""

            result = {
                "title": title,
                "authors": authors,
                "year": year,
                "venue": venue,
                "is_preprint": is_preprint,
                "influence_score": round(float(influence_score), 1) if influence_score else 0.0,
                "url": url
            }

            await set_cached(cache_key, "openalex", result, ttl_seconds=7*86400)
            return result

        except Exception as exc:
            logger.error("OpenAlex request failed for query '%s': %s", query, exc)
            return None

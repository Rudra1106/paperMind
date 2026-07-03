"""
app/pipelines/wiki_pipeline.py

Concurrent Wikipedia enrichment for concept definitions and resource URLs.

Key correction from plan Part 4 Section 6:
  wikipedia-api is a SYNCHRONOUS library. Running it directly inside an
  async function blocks the entire event loop for each HTTP call, which
  silently defeats asyncio.gather()'s concurrency — all lookups queue
  one after another despite the async syntax.

  Fix: wrap every sync call in asyncio.to_thread(), which runs it in
  a thread pool so requests genuinely overlap. For 20 concepts this is
  the difference between ~20 seconds and ~2 seconds.

return_exceptions=True in gather() means a single missing Wikipedia page
(common for niche ML terms) doesn't abort the entire enrichment batch.
"""

import asyncio
import logging

import wikipediaapi

from app.utils.cache_manager import wiki_cache
from app.utils.canonical import canonical

logger = logging.getLogger(__name__)

# Single module-level Wikipedia client
_wiki = wikipediaapi.Wikipedia(
    user_agent="PaperMind/1.0 (https://github.com/papermind; contact@papermind.dev)",
    language="en",
)


def _fetch_page_sync(concept_name: str) -> dict:
    """
    Synchronous Wikipedia fetch — runs in a thread pool via asyncio.to_thread.
    Returns a dict with 'definition' and 'resource_urls', or empty values if
    no matching page is found.
    """
    page = _wiki.page(concept_name)

    if not page.exists():
        # Try with the concept name formatted differently
        formatted = concept_name.replace("_", " ").title()
        page = _wiki.page(formatted)

    if not page.exists():
        return {"definition": None, "resource_urls": []}

    # Take the first 2 sentences as the definition
    sentences = page.summary.split(". ")
    definition = ". ".join(sentences[:2]).strip()
    if definition and not definition.endswith("."):
        definition += "."

    # page.links gives related Wikipedia article titles — useful as concept
    # cross-references in the roadmap UI. We take up to 5.
    # page.fullurl is the article's own URL, always available as a resource link.
    resource_urls = [page.fullurl] + list(page.links.keys())[:4]

    return {"definition": definition, "resource_urls": resource_urls}


async def fetch_wikipedia(concept_name: str) -> dict:
    """
    Async wrapper: check cache first, then fetch in a thread pool.
    Cache key is the canonical form so "Multi-Head Attention" and
    "multi_head_attention" both hit the same cached entry.
    """
    key = canonical(concept_name)
    cached = wiki_cache.get(key)
    if cached:
        return cached

    result = await asyncio.to_thread(_fetch_page_sync, concept_name)
    wiki_cache.set(key, result)
    return result


async def enrich_all(concept_names: list[str]) -> dict[str, dict]:
    """
    Enrich all concepts concurrently.

    Any failed lookup degrades to an empty result rather than stopping
    the whole pipeline. The concept still gets ingested — it just won't
    have a Wikipedia definition or external URLs.
    """
    results = await asyncio.gather(
        *[fetch_wikipedia(name) for name in concept_names],
        return_exceptions=True,
    )

    enriched: dict[str, dict] = {}
    for name, result in zip(concept_names, results):
        if isinstance(result, Exception):
            logger.warning("Wikipedia enrichment failed for '%s': %s", name, result)
            enriched[canonical(name)] = {"definition": None, "resource_urls": []}
        else:
            enriched[canonical(name)] = result

    return enriched

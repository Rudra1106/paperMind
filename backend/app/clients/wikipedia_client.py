# -*- coding: utf-8 -*-
"""
app/clients/wikipedia_client.py

Wikipedia API client with shared Postgres caching.
Fetches definitions and links concurrently in threads to prevent blocking.

Cleanup pipeline:
  1. Strip raw MediaWiki LaTeX: {\\displaystyle ...} blocks (multiline safe).
  2. Strip stray unicode math symbols (↦, →, ∑, etc.) left as artifacts.
  3. Strip doubled variable name patterns from MediaWiki rendering.
  4. Truncate to first 2 clean sentences.
  5. Minimum length guard: < 20 chars → treat as failed lookup.
"""

import asyncio
import logging
import re
import wikipediaapi
from app.utils.canonical import canonical
from app.services.external_cache import get_cached, set_cached, CACHE_VERSION

logger = logging.getLogger(__name__)

# Single module-level Wikipedia client
_wiki = wikipediaapi.Wikipedia(
    user_agent="PaperMind/1.0 (https://github.com/papermind; contact@papermind.dev)",
    language="en",
)

_wiki_semaphore = asyncio.Semaphore(10)


# ── Definition cleanup ────────────────────────────────────────────────────────

# Compiled once at import time for performance.
_RX_DISPLAYSTYLE = re.compile(r'\{\\displaystyle[^}]*(?:\{[^}]*\})*[^}]*\}', re.DOTALL)
_RX_LATEX_CURLY  = re.compile(r'\{[^}]{0,120}\}')          # residual {…} blocks
_RX_UNICODE_MATH = re.compile(r'[↦→←↔⟹⟺∑∫√∂∇∏±≤≥≠≈∈∉∧∨¬⊕⊗]')
_RX_SUBSCRIPT    = re.compile(r'\b([a-zA-Z])\s+\1\b')      # doubled var: "x x"
_RX_BACKSLASH    = re.compile(r'\\[a-zA-Z]+')               # \mapsto, \rightarrow
_RX_MULTI_SPACE  = re.compile(r'  +')


def _clean_definition(raw: str) -> str | None:
    """
    Clean a raw Wikipedia summary string into a short, human-readable definition.
    Returns None if the cleaned result is too short to be meaningful.
    """
    text = raw

    # 1. Strip {\\displaystyle ...} — the most common LaTeX artifact
    text = _RX_DISPLAYSTYLE.sub('', text)

    # 2. Strip residual {…} blocks (e.g. from nested math)
    # Repeat until stable (nested braces can leave outer shells behind)
    prev = None
    while prev != text:
        prev = text
        text = _RX_LATEX_CURLY.sub('', text)

    # 3. Strip backslash commands like \mapsto, \rightarrow
    text = _RX_BACKSLASH.sub('', text)

    # 4. Strip unicode math arrows and operators left as raw text
    text = _RX_UNICODE_MATH.sub('', text)

    # 5. Strip doubled variable name artifacts ("x x" → "x")
    text = _RX_SUBSCRIPT.sub(r'\1', text)

    # 6. Normalise whitespace
    text = _RX_MULTI_SPACE.sub(' ', text).strip()

    # 7. Take first 2 sentences
    sentences = [s.strip() for s in text.split('. ') if s.strip()]
    two = '. '.join(sentences[:2]).strip()
    if two and not two.endswith('.'):
        two += '.'

    # 8. Minimum-length guard — if less than 20 chars, treat as garbage
    if len(two) < 20:
        return None

    return two


# ── Sync page fetch (runs in thread pool) ────────────────────────────────────

def _fetch_page_sync(title: str, original_concept: str = "") -> dict:
    """Synchronous fetch running inside thread pool."""
    page = _wiki.page(title)

    if not page.exists():
        return {"definition": None, "resource_urls": []}

    raw_summary = page.summary or ""
    definition = _clean_definition(raw_summary)

    # If the returned page title differs significantly from the requested
    # concept, label the definition so users know the source.
    if (
        definition
        and original_concept
        and original_concept.lower() not in page.title.lower()
    ):
        definition = f"[From Wikipedia: {page.title}] {definition}"

    # Build resource URL list: main article + up to 4 related links
    resource_urls = [page.fullurl]
    for link_title in list(page.links.keys())[:4]:
        safe_title = link_title.replace(" ", "_")
        resource_urls.append(f"https://en.wikipedia.org/wiki/{safe_title}")

    return {"definition": definition, "resource_urls": resource_urls}


# ── Public async API ──────────────────────────────────────────────────────────

async def get_definition(concept_name: str, domain_context: str = "") -> dict:
    """
    Get Wikipedia summary and links. Uses shared Postgres external cache.

    Cache key format: {CACHE_VERSION}:wiki:{canonical_name}[:{canonical_domain}]
    TTL: 30 days.

    Falls through to LLM fallback (handled by enrichment_agent) when
    the cleaned definition is None/empty — this function returns
    {"definition": None, "resource_urls": []} in that case.
    """
    key = f"{CACHE_VERSION}:wiki:{canonical(concept_name)}"
    if domain_context:
        key += f":{canonical(domain_context)}"

    cached = await get_cached(key)
    if cached:
        # Defend against stale cache entries that slipped through with None
        if cached.get("definition"):
            return cached

    # 1. Disambiguated Wikipedia search: prefer domain-qualified query
    search_query = f"{concept_name} {domain_context}".strip() if domain_context else concept_name

    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": search_query,
        "format": "json",
        "utf8": "1",
        "srlimit": 1,
    }

    target_title = concept_name
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("query", {}).get("search", [])
                if results:
                    target_title = results[0]["title"]
    except Exception as exc:
        logger.error("Wikipedia search failed for '%s': %s", concept_name, exc)

    # 2. Fetch and clean the page
    # Ensure we don't exceed the underlying requests connection pool of 10
    async with _wiki_semaphore:
        result = await asyncio.to_thread(_fetch_page_sync, target_title, concept_name)

    # Only cache if we got a meaningful definition
    if result.get("definition"):
        await set_cached(key, "wikipedia", result, ttl_seconds=30 * 86400)
    else:
        logger.debug(
            "Wikipedia returned empty/garbage definition for '%s' (page: '%s') — not caching.",
            concept_name,
            target_title,
        )

    return result

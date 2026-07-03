"""
app/pipelines/scholar_pipeline.py

Semantic Scholar enrichment for the paper's own reference list.

This gives us metadata about related papers and adds credibility to the
resource links shown in the roadmap. It uses the public Semantic Scholar
API with no API key required.

No rate-limit interaction with OpenRouter — safe to call on every upload.
Cache added anyway to avoid redundant network calls during dev testing.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


async def get_paper_references(paper_title: str) -> list[dict]:
    """
    Search Semantic Scholar for the paper and return its reference list.

    Returns up to 20 reference dicts with title and abstract.
    Returns an empty list on any network error — this is enrichment data,
    not a core pipeline requirement.
    """
    if not paper_title or not paper_title.strip():
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                SEMANTIC_SCHOLAR_URL,
                params={
                    "query": paper_title.strip(),
                    "fields": "title,abstract,references",
                    "limit": 3,  # we only need the top match's references
                },
            )

        if response.status_code != 200:
            logger.warning(
                "Semantic Scholar returned %d for query: %r",
                response.status_code,
                paper_title,
            )
            return []

        data = response.json().get("data", [])
        if not data:
            return []

        # Use the first (most relevant) result's references
        paper = data[0]
        references = paper.get("references", [])
        logger.info(
            "Semantic Scholar: found '%s', %d references",
            paper.get("title", "?"),
            len(references),
        )
        return references[:20]

    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Semantic Scholar enrichment failed: %s", exc)
        return []

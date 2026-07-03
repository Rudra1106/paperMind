"""
app/utils/cache_manager.py

Two simple JSON-file caches.

  concepts_cache  — keyed by MD5(PDF bytes). Stores full concept+edge results.
                    A re-uploaded paper skips the LLM pipeline entirely.

  wiki_cache      — keyed by canonical concept name. Wikipedia summaries are
                    stable; re-fetching them wastes time and defeats the point
                    of concurrent enrichment.

These are intentionally simple. A real production system would use Redis or
a proper database, but for a hackathon these are sufficient and auditable.
The JSONCache.set() behaviour (full-file rewrite on every write) is noted as
a known simplification in the plan (Part 2, Section 9).
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".papermind_cache")
CACHE_DIR.mkdir(exist_ok=True)


class JSONCache:
    def __init__(self, filename: str) -> None:
        self.path = CACHE_DIR / filename
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Cache file %s is corrupt; starting fresh. (%s)", self.path, exc)
                self._data = {}

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def set(self, key: str, value: dict) -> None:
        self._data[key] = value
        try:
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to write cache file %s: %s", self.path, exc)

    def __contains__(self, key: str) -> bool:
        return key in self._data


# Module-level singletons — imported directly by the pipelines.
concepts_cache = JSONCache("concepts_cache.json")
wiki_cache = JSONCache("wiki_cache.json")
alias_map_cache = JSONCache("alias_map.json")


def get_paper_result(pdf_hash: str) -> dict | None:
    """Return cached concept+edge result for a PDF hash, or None."""
    return concepts_cache.get(pdf_hash)


def save_paper_result(pdf_hash: str, result: dict) -> None:
    """Persist full concept+edge result so re-uploads are instant."""
    concepts_cache.set(pdf_hash, result)

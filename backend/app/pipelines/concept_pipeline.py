"""
app/pipelines/concept_pipeline.py

Drives the two LLM calls that produce the concept graph for a paper:
  1. Concept extraction (Prompt 1) → list of concepts with category and aliases
  2. Dependency mapping (Prompt 2) → directed prerequisite edges

The cycle guard runs immediately after dependency mapping — before anything
reaches the topological sort. A cycle that reaches the sort is a hard crash
at demo time (plan Part 1 Section 4.4 / Part 4 Section 4).

All concept names are canonicalized at the earliest possible point so
nothing downstream ever has to think about casing or punctuation.
"""

import json
import logging

from app.prompts.extraction import CONCEPT_EXTRACTION_PROMPT, DEPENDENCY_MAPPING_PROMPT
from app.services.llm_client import call_llm_for_json
from app.utils.canonical import canonical
from app.utils.cache_manager import alias_map_cache

logger = logging.getLogger(__name__)


# ── Alias resolution ──────────────────────────────────────────────────────────

def resolve_aliases(concepts: list[dict]) -> list[dict]:
    """
    Check the local alias map before creating a new canonical name.
    If "MHA" maps to "multi_head_attention" already, don't create a new node.

    Also updates the alias map with any new aliases returned by the extraction.
    """
    for concept in concepts:
        canonical_name = canonical(concept["name"])
        aliases = concept.get("aliases", [])

        # Check if any alias already maps to a known canonical name
        for alias in aliases:
            alias_key = canonical(alias)
            existing = alias_map_cache.get(alias_key)
            if existing:
                logger.info(
                    "Alias collision: '%s' → resolving to existing '%s'",
                    concept["name"],
                    existing["canonical_name"],
                )
                canonical_name = existing["canonical_name"]
                break

        concept["canonical_name"] = canonical_name

        # Register this concept's aliases so future papers can resolve them
        for alias in aliases:
            alias_key = canonical(alias)
            if not alias_map_cache.get(alias_key):
                alias_map_cache.set(alias_key, {"canonical_name": canonical_name})

    return concepts


# ── Cycle detection ───────────────────────────────────────────────────────────

def validate_and_break_cycles(edges: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    DFS-based cycle detection on the dependency graph.

    When a cycle is found, the edge that closes it is dropped and logged.
    This must run before the edges reach the topological sort — a cycle
    there is an infinite loop at demo time.

    Recursion depth is bounded by concept count (15-30 per paper),
    so plain recursion is safe here.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in edges}
    dropped: list[tuple[str, str]] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        for prereq in list(edges.get(node, [])):
            if prereq not in color:
                continue  # prerequisite not in this concept list
            if color[prereq] == GRAY:
                # This edge closes a cycle — drop it
                edges[node].remove(prereq)
                dropped.append((node, prereq))
                continue
            if color[prereq] == WHITE:
                dfs(prereq)
        color[node] = BLACK

    for node in list(edges.keys()):
        if color.get(node) == WHITE:
            dfs(node)

    if dropped:
        logger.warning(
            "[cycle guard] Dropped %d edge(s) to break cycles: %s",
            len(dropped),
            dropped,
        )

    return edges


# ── Extraction pipeline ───────────────────────────────────────────────────────

async def extract_concepts(text_slice: str) -> dict:
    """
    Run Prompt 1 to extract concepts from the paper's key sections.

    Returns the full parsed JSON including paper_title, core_contribution,
    and the concepts list (with canonical_name added to each).
    """
    prompt = CONCEPT_EXTRACTION_PROMPT.format(abstract_intro_methodology=text_slice)
    parsed = await call_llm_for_json(
        prompt,
        system="You are a precise technical concept extractor. Return only the JSON described.",
        temperature=0.2,
    )

    if "concepts" not in parsed:
        raise ValueError("Concept extraction response missing 'concepts' key")

    # Canonicalize immediately — nothing downstream touches raw names
    parsed["concepts"] = resolve_aliases(parsed["concepts"])
    return parsed


async def map_dependencies(concepts: list[dict]) -> dict[str, list[str]]:
    """
    Run Prompt 2 to build the directed prerequisite graph.

    Returns a dict: canonical_name → [list of canonical_name prerequisites].
    Cycle-validated before returning.
    """
    names = [c["canonical_name"] for c in concepts]
    prompt = DEPENDENCY_MAPPING_PROMPT.format(
        json_list_of_concept_names=json.dumps(names, indent=2)
    )
    parsed = await call_llm_for_json(
        prompt,
        system="You are a precise dependency-graph builder. Return only the JSON described.",
        temperature=0.2,
    )

    if "edges" not in parsed:
        raise ValueError("Dependency mapping response missing 'edges' key")

    # Build canonical edge map — canonicalize both concept and prereq names
    raw_edges = parsed["edges"]
    edge_map: dict[str, list[str]] = {}
    for entry in raw_edges:
        concept_key = canonical(entry.get("concept", ""))
        prereqs = [canonical(r) for r in entry.get("requires", [])]
        if concept_key:
            edge_map[concept_key] = prereqs

    return validate_and_break_cycles(edge_map)

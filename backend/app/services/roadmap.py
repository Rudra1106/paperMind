# -*- coding: utf-8 -*-
"""
app/services/roadmap.py

Gap analysis and topological roadmap generation.

The gap: the difference between every concept a paper requires and the
subset the user already understands (confidence >= threshold).

The roadmap: the gap concepts ordered so prerequisites always come before
the concepts that depend on them, with lowest-confidence concepts surfaced
first within each valid ordering (plan Part 1 Section 6).

This is the "real graph reasoning" that separates PaperMind from generic
RAG chatbots — make sure the Day-3 verification check confirms that no
concept appears before its prerequisite in the output list.
"""

import logging
from collections import deque

from app.utils.canonical import canonical

logger = logging.getLogger(__name__)

# Concepts below this confidence threshold are considered gaps.
GAP_THRESHOLD = 0.6

# How priority labels map to sort order (lower = higher priority).
PRIORITY_RANK = {
    "critical": 0,   # confidence == 0.0 — never encountered
    "high": 1,       # confidence < 0.4
    "medium": 2,     # confidence < 0.59
    "almost_there": 3,  # 0.59 <= confidence < 0.6
}


def _priority_label(confidence: float) -> str:
    if confidence == 0.0:
        return "critical"
    if confidence < 0.4:
        return "high"
    if confidence < GAP_THRESHOLD:
        return "medium"
    return "almost_there"


def compute_gap(
    paper_concepts: list[dict],
    user_confidence: dict[str, float],
    threshold: float = GAP_THRESHOLD,
) -> list[dict]:
    """
    Return the subset of paper_concepts where the user's confidence is below
    the threshold, annotated with priority labels.

    Args:
        paper_concepts: Concept dicts from the paper, each with 'canonical_name'.
        user_confidence: Flat map of canonical_name → float (0.0 – 1.0).
        threshold: Concepts with confidence < threshold are gaps.

    Returns:
        List of gap concept dicts (same structure as input, with confidence and
        priority fields added).
    """
    gaps = []
    for concept in paper_concepts:
        cname = concept["canonical_name"]
        confidence = user_confidence.get(cname, 0.0)
        if confidence < threshold:
            gaps.append({
                **concept,
                "confidence": confidence,
                "priority": _priority_label(confidence),
            })

    logger.info(
        "Gap analysis: %d / %d concepts are below threshold %.1f",
        len(gaps),
        len(paper_concepts),
        threshold,
    )
    return gaps


def phased_topological_roadmap(
    gap_concepts: list[dict],
    edges: dict[str, list[str]],
) -> list[dict]:
    """
    Order gap concepts using Kahn's algorithm, grouping them into discrete 
    depth-based phases (modules). Concepts that can be learned in parallel 
    are grouped into the same phase.
    
    Args:
        gap_concepts: Output of compute_gap() — annotated with priority.
        edges: Full edge map (canonical_name → [prereq canonical_names]).
               Only edges between gap concepts are used.

    Returns:
        List of module dictionaries containing phase number, title, and concepts.
    """
    if not gap_concepts:
        return []

    gap_names = {c["canonical_name"] for c in gap_concepts}
    by_name = {c["canonical_name"]: c for c in gap_concepts}

    # Build in-degree count and adjacency list restricted to gap concepts
    in_degree: dict[str, int] = {n: 0 for n in gap_names}
    graph: dict[str, list[str]] = {n: [] for n in gap_names}

    for concept_name, prereqs in edges.items():
        if concept_name not in gap_names:
            continue
        for prereq in prereqs:
            if prereq in gap_names:
                graph[prereq].append(concept_name)
                in_degree[concept_name] += 1

    # Seed the queue with zero-in-degree concepts
    ready = [n for n in gap_names if in_degree[n] == 0]

    modules: list[dict] = []
    phase_index = 1
    visited = set()

    while ready:
        # Sort current phase concepts by priority for display order within the module
        ready.sort(key=lambda n: PRIORITY_RANK.get(by_name[n].get("priority", "medium"), 2))
        
        phase_concepts = [by_name[n] for n in ready]
        modules.append({
            "phase": phase_index,
            "title": f"Phase {phase_index}",
            "concepts": phase_concepts
        })
        visited.update(ready)

        newly_ready = []
        for current in ready:
            for neighbour in graph[current]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    newly_ready.append(neighbour)

        ready = newly_ready
        phase_index += 1

    # Detect if any concepts were stranded by a cycle that slipped through
    if len(visited) < len(gap_names):
        unvisited = gap_names - visited
        logger.warning(
            "Topological sort did not reach %d concept(s): %s. "
            "This suggests a residual cycle — appending them at end.",
            len(unvisited),
            unvisited,
        )
        unvisited_list = [by_name[name] for name in unvisited]
        unvisited_list.sort(key=lambda c: PRIORITY_RANK.get(c.get("priority", "medium"), 2))
        
        modules.append({
            "phase": phase_index,
            "title": f"Phase {phase_index} (Cyclic Residuals)",
            "concepts": unvisited_list
        })

    return modules

async def generate_roadmap_titles_async(modules: list[dict], cache_dict: dict, cache_key: tuple, paper_title: str) -> None:
    """
    Fire-and-forget background task to generate rich titles for each phase 
    using an LLM. Once generated, updates the modules in the cache.
    """
    from app.services.llm_client import call_llm_for_json
    import json

    try:
        # Prepare a lightweight summary of phases for the LLM
        phase_summaries = []
        for m in modules:
            concept_names = [c.get("display_name") or c.get("name") for c in m["concepts"]]
            phase_summaries.append({"phase": m["phase"], "concepts": concept_names})

        prompt = (
            f"Generate concise, engaging, and descriptive titles for a learning roadmap on '{paper_title}'.\n"
            "Each phase contains the following concepts to be learned:\n"
            f"{json.dumps(phase_summaries, indent=2)}\n\n"
            "Return a JSON object mapping phase integers to title strings. Example: {\"1\": \"Foundations of Vectors\", \"2\": \"Self-Attention\"}"
        )

        parsed = await call_llm_for_json(
            prompt,
            system="You are an expert curriculum designer. Return only the requested JSON mapping.",
            temperature=0.4
        )

        # Update the cache
        if cache_key in cache_dict:
            ts, cached_response = cache_dict[cache_key]
            
            # Map the generated titles back to the modules
            for m in cached_response.modules:
                str_phase = str(m.phase)
                if str_phase in parsed:
                    m.title = parsed[str_phase]

            # Update cache timestamp to keep it fresh
            import time
            cache_dict[cache_key] = (time.time(), cached_response)
            logger.info("Successfully updated roadmap titles in background cache for %s", cache_key)

    except Exception as e:
        logger.warning("Background title generation failed: %s", e)

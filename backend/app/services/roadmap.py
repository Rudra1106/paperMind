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


def topological_roadmap(
    gap_concepts: list[dict],
    edges: dict[str, list[str]],
) -> list[dict]:
    """
    Order gap concepts using a modified Kahn's algorithm (BFS topological sort)
    with confidence priority as a tiebreaker.

    Priority: prerequisites come before the concepts that depend on them.
    Within concepts that have no ordering constraint between them, we emit
    the lowest-confidence (most critical) concept first so learners tackle
    their biggest gaps earliest.

    Concepts in the edge map that are NOT in the gap list are skipped —
    they're known concepts that don't need to be studied.

    Args:
        gap_concepts: Output of compute_gap() — annotated with priority.
        edges: Full edge map (canonical_name → [prereq canonical_names]).
               Only edges between gap concepts are used.

    Returns:
        gap_concepts, reordered. Same dict structure, same fields.
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

    # Seed the queue with zero-in-degree concepts, sorted by priority
    ready = deque(
        sorted(
            [n for n in gap_names if in_degree[n] == 0],
            key=lambda n: PRIORITY_RANK[by_name[n]["priority"]],
        )
    )

    ordered: list[dict] = []
    while ready:
        current = ready.popleft()
        ordered.append(by_name[current])

        newly_ready = []
        for neighbour in graph[current]:
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                newly_ready.append(neighbour)

        # Re-sort the queue including newly unblocked concepts
        all_ready = list(ready) + newly_ready
        ready = deque(
            sorted(all_ready, key=lambda n: PRIORITY_RANK[by_name[n]["priority"]])
        )

    # Detect if any concepts were stranded by a cycle that slipped through
    if len(ordered) < len(gap_names):
        unvisited = gap_names - {c["canonical_name"] for c in ordered}
        logger.warning(
            "Topological sort did not reach %d concept(s): %s. "
            "This suggests a residual cycle — appending them at end.",
            len(unvisited),
            unvisited,
        )
        for name in unvisited:
            ordered.append(by_name[name])

    return ordered

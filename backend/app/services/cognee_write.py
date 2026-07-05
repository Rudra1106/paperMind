# -*- coding: utf-8 -*-
"""
app/services/cognee_write.py

Writes extracted concepts and their dependency edges into Cognee's graph
using typed DataPoints rather than guided-text remember().

Why not remember() here (plan Part 4 Section 0 and 5):
  remember() internally calls cognify() which calls an LLM to re-extract
  entities from the text we hand it. We've already extracted them with our
  own prompts. Paying for the same extraction twice is wasteful and
  introduces a risk of the internal LLM distorting our carefully validated
  edges.

  add_data_points() uses only Cognee's local fastembed embedding model to
  index the fields declared in model_config — no LLM call at all for
  paper_concepts ingestion.

Caveats noted in plan Part 4 Section 5:
  1. The list-of-prerequisites edge wiring pattern (node.requires = (edge, [list]))
     needs a live Day-1 smoke test to confirm it works as expected. The single-
     target form is the only one shown in the docs.
  2. Standalone add_data_points() nodes have no dataset tag, so forget(dataset=...)
     cannot clean them up. This is acceptable for paper_concepts because that
     dataset is append-only — we never need to delete individual concept nodes.
"""

import logging
from typing import Any

import cognee
from cognee.infrastructure.engine import DataPoint
from pydantic import SkipValidation

from app.models.cognee_models import (
    ConceptNode,
    PrerequisiteNode,
    PaperSpecificCoinageNode,
    MathConstructNode,
    CitedWorkNode,
)

logger = logging.getLogger(__name__)


async def write_paper_to_cognee(
    concepts: list[dict],
    edges: dict[str, list[str]],
    enriched: dict[str, dict],
    paper_id: str,
    user_id: str = "default",
) -> None:
    """
    Build ConceptNode DataPoints and write them to Cognee's graph.

    Steps:
      1. Create a ConceptNode for each extracted concept.
      2. Wire requires edges now that every node exists (avoids forward-reference issues).
      3. Write all nodes in one add_data_points() call.

    Args:
        concepts: List of concept dicts from concept_pipeline.extract_concepts().
                  Each has canonical_name, name, category, brief_context.
        edges: Cycle-validated edge map from concept_pipeline.map_dependencies().
               canonical_name → [list of canonical_name prerequisites].
        enriched: Wikipedia enrichment dict from wiki_pipeline.enrich_all().
                  canonical_name → {definition, resource_urls}.
        paper_id: UUID for this paper upload — stored on each node for later retrieval.
    """
    # Step 1: build nodes
    nodes: dict[str, ConceptNode] = {}
    for concept in concepts:
        cname = concept["canonical_name"]
        wiki_data = enriched.get(cname, {})

        definition = wiki_data.get("definition") or concept.get("brief_context", "")
        if definition:
            definition = definition[:1000]
            
        resource_urls = wiki_data.get("resource_urls", [])
        if resource_urls:
            resource_urls = resource_urls[:3]

        category = concept.get("category", "prerequisite")
        
        # Select the appropriate native Node Set (subclass) based on category
        if category == "prerequisite":
            node_class = PrerequisiteNode
        elif category == "paper_specific_term" or category == "paper_specific_coinage":
            node_class = PaperSpecificCoinageNode
        elif category == "math_construct":
            node_class = MathConstructNode
        elif category == "cited_work":
            node_class = CitedWorkNode
        else:
            node_class = ConceptNode

        nodes[cname] = node_class(
            name=cname,
            display_name=concept["name"],
            definition=definition,
            category=category,
            paper_id=paper_id,
            resource_urls=resource_urls,
        )

    # Step 2: wire requires edges
    # The plan notes the multi-target edge pattern needs smoke-testing.
    # We use the safe single-edge-per-pair approach to be explicit.
    for concept_name, prereq_names in edges.items():
        node = nodes.get(concept_name)
        if not node:
            continue

        prereq_nodes = [nodes[p] for p in prereq_names if p in nodes]
        if not prereq_nodes:
            continue

        try:
            from cognee.infrastructure.engine.models.Edge import Edge
            edge = Edge(relationship_type="requires", weight=1.0)

            if len(prereq_nodes) == 1:
                node.requires = (edge, prereq_nodes[0])
            else:
                node.requires = (edge, prereq_nodes)
        except ImportError:
            # Fallback: if Edge import path changes between cognee versions,
            # store as a list of names and log a warning rather than crashing.
            logger.warning(
                "Could not import cognee Edge model. Storing requires as name list for '%s'.",
                concept_name,
            )
            node.requires = prereq_names

    # Step 3: write to graph
    try:
        from cognee.tasks.storage import add_data_points
        await add_data_points(list(nodes.values()))
        logger.info(
            "Wrote %d ConceptNode(s) for paper %s to Cognee graph.",
            len(nodes),
            paper_id,
        )
    except Exception as exc:
        # If add_data_points() is unavailable or the Edge wiring fails,
        # fall back to remember() with guided text for each concept.
        # This costs extra LLM calls but keeps the pipeline functional.
        logger.error(
            "add_data_points() failed (%s). Falling back to guided-text remember().",
            exc,
        )
        await _fallback_remember_all(nodes, paper_id, user_id)


async def _fallback_remember_all(nodes: dict[str, ConceptNode], paper_id: str, user_id: str = "default") -> None:
    """
    Fallback: ingest concepts via cognee.remember() with guided text.
    Used if add_data_points() is unavailable. Costs extra LLM calls.
    """
    for cname, node in nodes.items():
        lines = [f"The concept '{cname}' is defined as: {node.definition}"]
        if node.resource_urls:
            lines.append(f"A learning resource for '{cname}' is at {node.resource_urls[0]}.")
        lines.append(f"The concept '{cname}' appears in paper '{paper_id}'.")
        text = "\n".join(lines)
        
        from cognee.modules.users.models import User
        import uuid
        cognee_user = User(id=uuid.UUID(user_id)) if user_id and user_id != "default" else None
        
        await cognee.remember(text, dataset_name="paper_concepts", user=cognee_user)

    logger.info("Fallback remember() completed for %d concepts.", len(nodes))

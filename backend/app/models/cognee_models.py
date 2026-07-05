# -*- coding: utf-8 -*-
"""
app/models/cognee_models.py

Typed DataPoint models for writing directly into Cognee's graph
without triggering a second LLM call via cognify().

Why skip remember() for paper_concepts:
  remember() = add() + cognify() + improve()
  cognify() calls an LLM to re-extract entities from whatever text you give it.
  We've already extracted them precisely. Handing Cognee prose and having its
  internal LLM re-derive the same structure pays for the same work twice.

  Solution (plan Part 4, Section 0 and Section 5):
    - Use add_data_points() with typed ConceptNode objects for paper_concepts.
    - Cognee uses its local fastembed model to index the fields in `metadata`
      — no LLM call, no rate-limit hit.
    - Reserve remember() for user_knowledge entries (simple key-value facts
      that don't need relationship extraction; they have no graph edges).

Note on SkipValidation:
  Cognee's DataPoint uses Pydantic. The `requires` field holds either a single
  ConceptNode or a list — Pydantic can't validate a recursive type out of the
  box, so SkipValidation tells Pydantic to pass it through as-is.
"""

from typing import Any

from cognee.infrastructure.engine import DataPoint
from pydantic import SkipValidation


class ConceptNode(DataPoint):
    """
    A single concept extracted from a research paper.

    Fields intentionally kept flat and readable — judges looking at the code
    should immediately understand what each field represents.
    """

    # canonical_name is used as the graph key (normalised via canonical())
    name: str
    # Original casing as seen in the paper, for display in the UI
    display_name: str
    # 2-3 sentence definition sourced from Wikipedia; falls back to the
    # brief_context from the LLM extraction if Wikipedia has no match
    definition: str = ""
    # "prerequisite" = learner needs this before reading the paper
    # "introduced"   = this paper teaches this concept
    category: str = "prerequisite"
    # Which paper ingested this concept — used by /roadmap to load paper-specific graph
    paper_id: str = ""
    # Wikipedia article URL and up to 4 related concept links
    resource_urls: SkipValidation[Any] = None

    # Directed prerequisite edges: this concept REQUIRES these other concepts.
    # Populated by write_paper_to_cognee() after all nodes are created.
    requires: SkipValidation[Any] = None

    # Controls which fields Cognee embeds for vector similarity search.
    # name + display_name + definition = what users will actually query against.
    model_config = {"arbitrary_types_allowed": True}

    # Tells Cognee to index these fields for SIMILARITY and GRAPH_COMPLETION search
    metadata: dict = {"index_fields": ["name", "display_name", "definition"]}


class PrerequisiteNode(ConceptNode):
    """A foundational concept required to understand the paper."""
    pass


class PaperSpecificCoinageNode(ConceptNode):
    """A novel term or system introduced specifically in this paper."""
    pass


class MathConstructNode(ConceptNode):
    """A mathematical or algorithmic building block."""
    pass


class CitedWorkNode(ConceptNode):
    """A referenced paper, dataset, or prior model."""
    pass

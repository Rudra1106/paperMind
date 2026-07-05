# -*- coding: utf-8 -*-
"""
app/agents/dependency_agent.py

Dependency Agent.
Maps topological dependencies between concepts, using Semantic Scholar citation
graph reference titles/abstracts as priors to build reliable prerequisite links.
Runs cycle detection and breaking before returning.
"""

import json
import logging
from app.services.llm_client import call_llm_for_json
from app.clients import semantic_scholar_client
from app.utils.canonical import canonical
from app.pipelines.concept_pipeline import validate_and_break_cycles

logger = logging.getLogger(__name__)

DEPENDENCY_ROUTER_PROMPT = """\
You are an expert at mapping the topological dependencies of machine learning concepts.
You identify which concepts must be understood BEFORE another concept can be grasped.

We have cross-referenced the Semantic Scholar citation graph for this paper. The following citation prior has been established:
<citation_priors>
{priors}
</citation_priors>

<instructions>
1. Read the <concept_list> below.
2. In <thinking> tags, identify which concepts in the list are strict prerequisites of others. Use the citation priors above to guide your reasoning.
3. In <answer> tags, output ONLY the JSON object described in <output_format>. Avoid circular dependencies.
</instructions>

<output_format>
{{
  "edges": [
    {{"concept": "concept_name", "requires": ["prereq_concept_1", "prereq_concept_2"]}}
  ]
}}
</output_format>

<concept_list>
{concept_names}
</concept_list>
"""

async def run(concepts: list[dict], arxiv_id: str | None = None) -> dict:
    """
    Run dependency mapping. If arXiv ID is available, pulls references
    from Semantic Scholar to establish citation priors.
    """
    logger.info("Dependency agent mapping concept relationships...")
    
    concept_names = [c["name"] for c in concepts]
    concept_canon_map = {canonical(c["name"]): c["name"] for c in concepts}
    
    # 1. Establish citation priors via Semantic Scholar
    priors = []
    if arxiv_id:
        try:
            logger.info("Fetching references for paper %s from Semantic Scholar...", arxiv_id)
            paper_data = await semantic_scholar_client.get_paper_by_arxiv_id(arxiv_id)
            if paper_data and "references" in paper_data:
                refs = paper_data["references"]
                for ref in refs[:15]:  # Limit to top 15 references to keep prompt size manageable
                    ref_title = ref.get("title", "")
                    ref_abs = ref.get("abstract", "") or ""
                    
                    # Scan references for mentions of our concepts
                    matched_concepts = []
                    for c_name in concept_names:
                        # Simple keyword matching
                        clean_name = c_name.replace("_", " ").lower()
                        if clean_name in ref_title.lower() or clean_name in ref_abs.lower():
                            matched_concepts.append(c_name)
                    
                    if matched_concepts:
                        priors.append(f"- Concept(s) {matched_concepts} likely introduced in referenced paper: \"{ref_title}\"")
        except Exception as exc:
            logger.error("Failed to build citation priors: %s", exc)

    priors_str = "\n".join(priors) if priors else "No direct citation prior could be found for this set of concepts."

    # 2. Call LLM for dependency mapping with reasoning enabled
    prompt = DEPENDENCY_ROUTER_PROMPT.format(
        priors=priors_str,
        concept_names=json.dumps(concept_names)
    )

    try:
        res = await call_llm_for_json(prompt, temperature=0.1, use_reasoning=True)
        edges = res.get("edges", [])
    except Exception as exc:
        logger.error("Dependency mapping LLM call failed: %s", exc)
        edges = []

    # 3. Format into adjacency list
    edge_map = {}
    for edge in edges:
        concept = canonical(edge.get("concept", ""))
        requires = [canonical(r) for r in edge.get("requires", [])]
        
        # Keep only valid concepts present in our list
        valid_requires = [r for r in requires if r in concept_canon_map]
        if concept in concept_canon_map and valid_requires:
            edge_map[concept] = valid_requires

    # Ensure all concepts exist in adjacency map
    for c in concept_canon_map.keys():
        if c not in edge_map:
            edge_map[c] = []

    # 4. Cycle guard
    clean_edge_map = validate_and_break_cycles(edge_map)

    # Keep edges keyed by canonical names — topological_roadmap() and endpoints.py
    # both index by canonical_name. Using display names here was the root cause
    # of the inverted roadmap (in-degree lookups never matched).
    final_edges = {}
    for k, v in clean_edge_map.items():
        final_edges[k] = list(v)  # canonical → [canonical]

    return {"edges": final_edges}

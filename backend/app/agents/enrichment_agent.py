# -*- coding: utf-8 -*-
"""
app/agents/enrichment_agent.py

Enrichment Agent (tool-calling router).
Decides which tool to invoke (Wikipedia, Semantic Scholar, Wolfram) for each 
extracted concept or equation, then dispatches the calls concurrently.
"""

import asyncio
import logging
from app.services.llm_client import call_llm_for_json
from app.clients import wikipedia_client, semantic_scholar_client, wolfram_client, openalex_client
from app.services import citation_registry
from app.utils.canonical import canonical

logger = logging.getLogger(__name__)

ENRICHMENT_ROUTER_PROMPT = """\
You are an API Routing Agent. You assign each concept or mathematical formula to the most appropriate API tool.

Available Tools:
1. "wikipedia": for standard mathematical operations, foundational computer science algorithms, and generic machine learning terms (e.g. "softmax", "gradient descent", "neural network", "backpropagation", "convolution").
2. "semantic_scholar": for named neural architectures, specific published models, papers, datasets, or libraries (e.g. "resnet-50", "bert", "imagenet", "adamw optimizer", "lora").
3. "wolfram": for inline math equations, formal derivations, coordinate calculations, or expressions that require evaluation (e.g. "E = mc^2", "f(x) = x^2", "sum_{i=1}^n i").
4. "none": for simple terms or concepts that do not require external verification or enrichment.

Your output format MUST be a JSON object inside <answer> tags:
<answer>
{
  "routing": [
    {
      "target": "name of concept or equation",
      "tool": "wikipedia" | "semantic_scholar" | "wolfram" | "none",
      "reason": "why this tool was chosen"
    }
  ]
}
</answer>

Concepts and Equations:
{targets}
"""

async def run(concepts: list[dict], equations: list[str], paper_title: str = "", paper_id: str = None) -> dict:
    """
    Run enrichment agent:
      1. Batch route concepts/equations to tools.
      2. Fetch definition, compute math, and aggregate.
      3. Returns enriched dictionary of results.
    """
    logger.info("Enrichment agent running routing loop...")
    
    # 1. Build targets list for LLM routing
    target_names = [c["name"] for c in concepts] + equations
    if not target_names:
        return {"concepts": {}}

    # Register the primary source citation first (Index 1)
    if paper_id:
        await citation_registry.register_citation(
            paper_id=paper_id,
            session_id=None,
            source_type="PrimarySource",
            title=paper_title or "Primary Paper Source",
            venue="PDF Document",
            is_preprint=False,
            influence_score=99.0
        )

    targets_str = "\n".join(f"- {name}" for name in target_names)
    prompt = ENRICHMENT_ROUTER_PROMPT.replace("{targets}", targets_str)

    # 2. Call routing agent
    try:
        routing_decision = await call_llm_for_json(prompt, temperature=0.1, use_reasoning=False)
        routing_list = routing_decision.get("routing", [])
    except Exception as exc:
        logger.error("Enrichment routing failed: %s. Falling back to default routing.", exc)
        routing_list = []

    # Map target -> tool
    routing_map = {item["target"]: item["tool"] for item in routing_list if "target" in item and "tool" in item}

    # 3. Dispatch calls concurrently
    tasks = []
    task_keys = []

    # Helper function to enrich single target
    async def enrich_target(target: str, is_equation: bool, category: str = None, existing_definition: str = None):
        if category == "paper_specific_term":
            tool = "none"
        else:
            tool = routing_map.get(target, "wikipedia" if not is_equation else "wolfram")
        
        # Safe fallback defaults
        enriched_data = {
            "definition": existing_definition,
            "resource_urls": [],
            "wolfram_result": None,
            "citation_index": None
        }

        # If it's a paper_specific_term, we instantly skip external fetching.
        if tool == "none":
            return enriched_data

        try:
            if tool == "wikipedia":
                res = await wikipedia_client.get_definition(target, domain_context=paper_title)
                if not enriched_data["definition"]:
                    enriched_data["definition"] = res.get("definition")
                enriched_data["resource_urls"] = res.get("resource_urls", [])
                
                # Register Wikipedia source in registry
                if paper_id and enriched_data["definition"] and enriched_data["resource_urls"]:
                    url = enriched_data["resource_urls"][0] if enriched_data["resource_urls"] else ""
                    idx = await citation_registry.register_citation(
                        paper_id=paper_id,
                        session_id=None,
                        source_type="Wikipedia",
                        title=f"Wikipedia: {target}",
                        url=url,
                        is_preprint=False,
                        influence_score=50.0
                    )
                    enriched_data["citation_index"] = idx

            elif tool == "semantic_scholar":
                # For concepts, search the semantic scholar database
                res = await semantic_scholar_client.search_concept(target)
                if res and "data" in res and len(res["data"]) > 0:
                    paper_match = None
                    from rapidfuzz import fuzz
                    for p in res["data"]:
                        p_title = p.get("title", "")
                        if fuzz.token_set_ratio(target.lower(), p_title.lower()) >= 65:
                            paper_match = p
                            break
                            
                    if not paper_match:
                        logger.warning("No relevant Semantic Scholar result found for '%s'. Fallback to next tool.", target)
                    else:
                        paper = paper_match
                        tldr = paper.get("tldr")
                        tldr_text = tldr.get("text") if tldr else None
                        if not enriched_data["definition"]:
                            enriched_data["definition"] = tldr_text or paper.get("abstract")
                        # Construct clean paper link
                        paper_id_ss = paper.get("paperId")
                        url = f"https://www.semanticscholar.org/paper/{paper_id_ss}" if paper_id_ss else ""
                        enriched_data["resource_urls"] = [url] if url else []
    
                        # Enrich citation card using OpenAlex
                        is_preprint = False
                        influence_score = 0.0
                        if paper.get("title"):
                            oa_res = await openalex_client.fetch_work_by_title_or_doi(paper["title"])
                            if oa_res:
                                is_preprint = oa_res.get("is_preprint", False)
                                influence_score = oa_res.get("influence_score", 0.0)
                                if oa_res.get("url"):
                                    url = oa_res["url"]
    
                        # Format authors
                        authors = []
                        for author_node in (paper.get("authors") or [])[:3]:
                            if author_node.get("name"):
                                authors.append(author_node["name"])
    
                        # Register citation in registry
                        if paper_id and enriched_data["resource_urls"]:
                            idx = await citation_registry.register_citation(
                                paper_id=paper_id,
                                session_id=None,
                                source_type="OpenAlex" if influence_score > 0 else "SemanticScholar",
                                title=paper.get("title", f"Scholar: {target}"),
                                authors=authors,
                                year=paper.get("year"),
                                venue=paper.get("venue") or "Academic Venue",
                                url=url,
                                is_preprint=is_preprint,
                                influence_score=influence_score
                            )
                            enriched_data["citation_index"] = idx

            elif tool == "wolfram":
                res = await wolfram_client.verify_math(target)
                if res:
                    enriched_data["wolfram_result"] = res
                    if not enriched_data["definition"]:
                        enriched_data["definition"] = f"Wolfram Evaluation: {res}"
            
            # If routed tool failed to find anything, try Wikipedia fallback for concepts
            if not is_equation and not enriched_data["definition"]:
                res = await wikipedia_client.get_definition(target, domain_context=paper_title)
                if res.get("definition"):
                    enriched_data["definition"] = res.get("definition")
                    enriched_data["resource_urls"] = res.get("resource_urls", [])
                    
                    if paper_id and enriched_data["resource_urls"]:
                        url = enriched_data["resource_urls"][0] if enriched_data["resource_urls"] else ""
                        idx = await citation_registry.register_citation(
                            paper_id=paper_id,
                            session_id=None,
                            source_type="Wikipedia",
                            title=f"Wikipedia: {target}",
                            url=url,
                            is_preprint=False,
                            influence_score=50.0
                        )
                        enriched_data["citation_index"] = idx

            # If still no definition, try LLM fallback
            if not is_equation and not enriched_data["definition"]:
                try:
                    from app.services.llm_client import call_llm
                    fallback_prompt = f"Provide a concise, 1-2 sentence definition for the machine learning concept '{target}' in the context of the paper '{paper_title}'. Output only the text definition."
                    fallback_def = await call_llm(fallback_prompt, temperature=0.3, use_reasoning=False)
                    if fallback_def and len(fallback_def) > 10:
                        enriched_data["definition"] = fallback_def.strip()
                except Exception as exc:
                    logger.error("LLM fallback failed for '%s': %s", target, exc)

        except Exception as e:
            logger.error("Error enriching target '%s' with tool '%s': %s", target, tool, e)

        return enriched_data

    for c in concepts:
        tasks.append(enrich_target(c["name"], is_equation=False, category=c.get("category"), existing_definition=c.get("definition")))
        task_keys.append(canonical(c["name"]))

    for eq in equations:
        tasks.append(enrich_target(eq, is_equation=True, category="math_construct"))
        task_keys.append(eq)

    # Gather all lookups concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    enriched_concepts = {}
    for key, result in zip(task_keys, results):
        if isinstance(result, Exception):
            logger.error("Failed to enrich target %s: %s", key, result)
            enriched_concepts[key] = {"definition": None, "resource_urls": [], "wolfram_result": None}
        else:
            enriched_concepts[key] = result

    return {"concepts": enriched_concepts}

# -*- coding: utf-8 -*-
"""
app/agents/extraction_agent.py

Extraction agent (Map-Reduce).
Extracts prerequisite and new concepts from a paper by chunking the full text,
running DeepSeek V4 Flash on each chunk in parallel, and aggregating the results.
"""

import logging
import asyncio
from collections import Counter
from app.services.llm_client import call_llm_for_json, validate_evidence_quotes
from app.prompts.extraction import CONCEPT_EXTRACTION_PROMPT
from app.pipelines.concept_pipeline import resolve_aliases

logger = logging.getLogger(__name__)

async def _extract_from_chunk(chunk: str, full_text: str) -> dict:
    prompt = CONCEPT_EXTRACTION_PROMPT.format(abstract_intro_methodology=chunk)
    try:
        result = await call_llm_for_json(
            prompt=prompt,
            temperature=0.1,
            use_reasoning=True
        )
        concepts = result.get("concepts", [])
        validated = validate_evidence_quotes(concepts, full_text)
        result["concepts"] = validated
        return result
    except Exception as exc:
        logger.error("LLM chunk concept extraction failed: %s", exc)
        return {"paper_title": "Unknown", "core_contribution": "", "concepts": []}

async def run(text_slice: str, full_text: str) -> dict:
    """
    Run the extraction agent using Map-Reduce.
    """
    logger.info("Extraction agent running Map-Reduce over full text...")
    
    # 1. Map step: Chunk the full text
    chunk_size = 15000  # roughly 3000-4000 tokens
    overlap = 1500
    
    chunks = []
    if len(full_text) <= chunk_size:
        chunks = [full_text]
    else:
        for i in range(0, len(full_text), chunk_size - overlap):
            chunks.append(full_text[i:i + chunk_size])
            
    logger.info("Split document into %d overlapping chunks", len(chunks))
    
    # 2. Run extraction concurrently
    tasks = [_extract_from_chunk(c, full_text) for c in chunks]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 3. Reduce step: Aggregate
    merged_concepts = []
    titles = []
    contributions = []
    
    for r in results:
        if isinstance(r, dict):
            if r.get("paper_title") and r["paper_title"] != "Unknown":
                titles.append(r["paper_title"])
            if r.get("core_contribution"):
                contributions.append(r["core_contribution"])
            merged_concepts.extend(r.get("concepts", []))
            
    # 4. Resolve aliases and deduplicate
    resolved = resolve_aliases(merged_concepts)
    
    deduped = {}
    for c in resolved:
        canonical_name = c["canonical_name"]
        if canonical_name not in deduped:
            deduped[canonical_name] = c
        else:
            # Merge aliases
            existing_aliases = set(deduped[canonical_name].get("aliases", []))
            new_aliases = set(c.get("aliases", []))
            deduped[canonical_name]["aliases"] = list(existing_aliases | new_aliases)
            # Keep the longest definition to ensure we don't lose detail
            existing_def = deduped[canonical_name].get("definition", "")
            new_def = c.get("definition", "")
            if len(new_def) > len(existing_def):
                deduped[canonical_name]["definition"] = new_def
            
    final_concepts = list(deduped.values())
    
    final_title = Counter(titles).most_common(1)[0][0] if titles else "Unknown"
    final_contrib = max(contributions, key=len) if contributions else ""
    
    return {
        "paper_title": final_title,
        "core_contribution": final_contrib,
        "concepts": final_concepts
    }

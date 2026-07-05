# -*- coding: utf-8 -*-
"""
app/agents/verification_agent.py

Verification Agent.
Runs cheap secondary validation passes:
  1. String-based evidence quote validation (drops hallucinated concepts).
  2. LLM-based definition contradiction check (detects semantic drift).
"""

import asyncio
import logging
from app.services.llm_client import call_llm_for_json, validate_evidence_quotes
from app.utils.canonical import canonical

logger = logging.getLogger(__name__)

CONTRADICTION_PROMPT = """\
You are a Scientific Verification Agent. You compare a concept's usage in a research paper with its standard Wikipedia or database definition.
Identify if the paper's usage contradicts the standard definition, or if there is a massive semantic drift.

<paper_usage>
"{evidence_quote}"
</paper_usage>

<standard_definition>
"{definition}"
</standard_definition>

Output your result in JSON inside <answer> tags:
<answer>
{{
  "is_contradictory": true | false,
  "explanation": "Provide a brief explanation if contradictory, else leave empty"
}}
</answer>
"""

async def run(concepts: list[dict], full_text: str) -> dict:
    """
    Run verification:
      1. Verifies that the evidence quote is physically present in the text.
      2. Compares the definition to the evidence quote to flag contradictions.
    """
    logger.info("Verification agent verifying evidence quotes and definitions...")
    
    # Step 1: Substring validation of evidence quotes
    valid_concepts = validate_evidence_quotes(concepts, full_text)

    # Step 2: Cross-definition contradiction checks
    # Run these in parallel to keep it fast
    tasks = []
    
    async def verify_concept_definition(concept: dict):
        # By default no contradiction
        concept["is_contradictory"] = False
        concept["contradiction_explanation"] = None
        
        quote = concept.get("evidence_quote")
        definition = concept.get("definition")
        
        if not quote or not definition:
            return concept
            
        prompt = CONTRADICTION_PROMPT.format(evidence_quote=quote, definition=definition)
        try:
            # Simple quick pass, no reasoning details needed
            res = await call_llm_for_json(prompt, temperature=0.0, use_reasoning=False)
            if res.get("is_contradictory"):
                concept["is_contradictory"] = True
                concept["contradiction_explanation"] = res.get("explanation")
                logger.warning("Contradiction detected for concept '%s': %s", concept["name"], res.get("explanation"))
        except Exception as exc:
            logger.error("Failed contradiction check for '%s': %s", concept["name"], exc)
            
        return concept

    for c in valid_concepts:
        tasks.append(verify_concept_definition(c))

    verified_concepts = await asyncio.gather(*tasks)
    return {"concepts": verified_concepts}

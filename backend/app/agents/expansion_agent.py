# -*- coding: utf-8 -*-
"""
app/agents/expansion_agent.py

Sub-Concept Expansion Agent.

Given a concept and its paper's chunk context, this agent uses an LLM to
identify the 3–5 mathematical or conceptual building blocks that a learner
MUST understand to deeply grasp the concept — the "graph of graphs" layer
below the roadmap.

For math-heavy sub-concepts (is_math=True), the agent extracts the core
formula and routes it through Wolfram|Alpha for a verified step-by-step
breakdown before returning.

Cache strategy:
  Key:  {CACHE_VERSION}:expand:{canonical_concept}:{paper_id}
  TTL:  30 days (sub-concept structure is stable per paper).

The cache lives in the shared external_cache table so repeat expansions
of the same concept in the same paper are instant.
"""

import json
import logging
from app.services.llm_client import call_llm_for_json
from app.clients import wolfram_client
from app.services.external_cache import get_cached, set_cached, CACHE_VERSION
from app.utils.canonical import canonical

logger = logging.getLogger(__name__)


# ── Prompts ───────────────────────────────────────────────────────────────────

EXPANSION_PROMPT = """\
You are an expert research scientist and pedagogy specialist.

Your task: Given a concept from a machine learning paper and relevant context,
identify the 3–5 foundational sub-concepts or mathematical building blocks that
a learner MUST understand to deeply grasp the target concept.

Think like a researcher teaching a PhD student who has general ML knowledge but
has never seen this specific concept before.

<instructions>
1. In <thinking> tags, analyse the concept and context. Identify the precise
   sub-topics that form its mathematical or conceptual substrate. Focus on:
   - Mathematical operations the concept is built from
   - Prior concepts it directly extends or assumes
   - Key notational or definitional terms
2. In <answer> tags, output ONLY the JSON described in <output_format>.
   No text before or after.
</instructions>

<output_format>
{{
  "sub_concepts": [
    {{
      "name": "short name, 2-4 words",
      "canonical_name": "snake_case",
      "definition": "1-2 sentence explanation, paper-grounded",
      "is_math": true | false,
      "formula": "LaTeX or plain-text formula if is_math=true, else null"
    }}
  ]
}}
</output_format>

<examples>
<example>
<concept>scaled dot-product attention</concept>
<answer>
{{
  "sub_concepts": [
    {{
      "name": "dot product similarity",
      "canonical_name": "dot_product_similarity",
      "definition": "The dot product between query and key vectors measures how aligned they are — higher dot product means higher raw attention score.",
      "is_math": true,
      "formula": "score(q, k) = q · k"
    }},
    {{
      "name": "softmax normalisation",
      "canonical_name": "softmax",
      "definition": "Converts raw scores into a valid probability distribution summing to 1, ensuring attention weights are non-negative and comparable across positions.",
      "is_math": true,
      "formula": "softmax(z_i) = exp(z_i) / sum(exp(z_j))"
    }},
    {{
      "name": "temperature scaling",
      "canonical_name": "scaling_factor",
      "definition": "The 1/√d_k factor prevents dot products from growing too large in high dimensions, which would push softmax into saturation regions with vanishing gradients.",
      "is_math": true,
      "formula": "Attention(Q,K,V) = softmax(QK^T / sqrt(d_k)) V"
    }},
    {{
      "name": "query key value decomposition",
      "canonical_name": "query_key_value",
      "definition": "The input is projected into three distinct vector spaces — queries (what we're looking for), keys (what each token offers), and values (what each token contributes).",
      "is_math": false,
      "formula": null
    }}
  ]
}}
</answer>
</example>
</examples>

<concept>{concept_name}</concept>

<paper_context>
{chunk_context}
</paper_context>
"""


# ── Core run function ─────────────────────────────────────────────────────────

async def run(
    concept_name: str,
    chunk_context: str,
    paper_id: str,
) -> dict:
    """
    Expand a concept into its sub-concepts.

    Args:
        concept_name:  Display name of the concept (e.g. "scaled dot-product attention").
        chunk_context: Relevant paper excerpts providing grounding (max ~2000 chars).
        paper_id:      The paper this concept comes from (used for cache partitioning).

    Returns:
        {
          "sub_concepts": [
            {
              "name": str,
              "canonical_name": str,
              "definition": str,
              "is_math": bool,
              "formula": str | None,
              "wolfram_result": str | None,   # present when is_math=True and Wolfram succeeds
            }
          ],
          "wolfram_verified": bool,   # True if at least one formula was verified
        }
    """
    canon = canonical(concept_name)
    cache_key = f"{CACHE_VERSION}:expand:{canon}:{paper_id}"

    cached = await get_cached(cache_key)
    if cached:
        logger.debug("Expansion cache hit for concept '%s' in paper %s", concept_name, paper_id)
        return cached

    logger.info("Expansion agent running for concept '%s'...", concept_name)

    # Trim context to avoid bloating the prompt
    trimmed_context = chunk_context[:2500] if chunk_context else "(no context available)"

    prompt = EXPANSION_PROMPT.format(
        concept_name=concept_name,
        chunk_context=trimmed_context,
    )

    try:
        result = await call_llm_for_json(prompt, temperature=0.2, use_reasoning=True)
        sub_concepts = result.get("sub_concepts", [])
    except Exception as exc:
        logger.error("Expansion LLM call failed for '%s': %s", concept_name, exc)
        sub_concepts = []

    # ── Wolfram verification for math sub-concepts ────────────────────────────
    wolfram_verified = False
    for sc in sub_concepts:
        sc.setdefault("wolfram_result", None)
        if sc.get("is_math") and sc.get("formula"):
            try:
                wolfram_res = await wolfram_client.verify_math(sc["formula"])
                if wolfram_res:
                    sc["wolfram_result"] = wolfram_res
                    wolfram_verified = True
                    logger.info(
                        "Wolfram verified formula for sub-concept '%s': %s",
                        sc["name"],
                        wolfram_res[:80],
                    )
            except Exception as exc:
                logger.warning("Wolfram check failed for sub-concept '%s': %s", sc["name"], exc)

    output = {
        "sub_concepts": sub_concepts,
        "wolfram_verified": wolfram_verified,
    }

    # Cache the fully resolved result
    if sub_concepts:
        await set_cached(cache_key, "expansion_agent", output, ttl_seconds=30 * 86400)

    return output

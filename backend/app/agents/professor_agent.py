# -*- coding: utf-8 -*-
"""
app/agents/professor_agent.py

Professor / Chat Agent.
Supports query-time cross-paper context, live Wolfram math tool calling,
proactive math question detection, and user confidence extraction in one turn.

Math upgrade (Phase 4):
  - _is_math_question(): regex + keyword detection to proactively route math Qs
  - _extract_formula_from_context(): lightweight LLM call to pull the relevant
    formula from paper chunks before asking Wolfram
  - verified_by_wolfram flag in the returned dict, surfaces as a frontend badge
"""

import json
import logging
import re
from app.services.llm_client import call_llm, extract_json
from app.clients import wolfram_client
from app.services import citation_registry
from app.prompts.professor import PROFESSOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# ── Math question detection ───────────────────────────────────────────────────

# Patterns that indicate the user is asking about a mathematical computation.
_MATH_SYMBOLS = re.compile(
    r'[\\\^\_∑∫√∂∇∏±≤≥≠≈∈∉∧∨⊕⊗·×÷]|'
    r'\b(softmax|argmax|exp|log|ln|tanh|relu|sigmoid|norm|det|trace|eigenvalue)\s*[\(\{]'
)

_MATH_PHRASES = re.compile(
    r'\b('
    r'how is .{1,40} (computed?|calculated?|derived?|defined?)|'
    r'what does (this|the) equation|'
    r'(derive|prove|show|compute|calculate|formula for|formula of)|'
    r'step[- ]by[- ]step|'
    r'mathematically|'
    r'what is [\w\s]{1,30} equal to|'
    r'\d+/\d+|'           # fractions like 1/√dk written as 1/sqrt
    r'sqrt|'
    r'\bdk\b|\bd_k\b'     # common Transformer notation
    r')',
    re.IGNORECASE,
)


def _is_math_question(message: str) -> bool:
    """
    Return True if the user message appears to be asking about a mathematical
    concept, formula, or computation.
    """
    return bool(_MATH_SYMBOLS.search(message) or _MATH_PHRASES.search(message))


async def _extract_formula_from_context(concept_hint: str, chunks: str) -> str | None:
    """
    Use a minimal, zero-temperature LLM call to extract the most relevant
    formula from the paper chunks for a given concept hint.
    Returns the formula string, or None if nothing suitable was found.
    """
    prompt = (
        f"From the following paper text, extract ONLY the single most relevant "
        f"mathematical formula or equation related to '{concept_hint}'. "
        f"Output just the formula text — no explanation, no prose.\n\n"
        f"Paper text:\n{chunks[:2000]}"
    )
    try:
        formula = await call_llm(prompt, temperature=0.0, use_reasoning=False)
        formula = formula.strip()
        # Reject if the LLM returned a long paragraph instead of a formula
        if formula and len(formula) < 300:
            return formula
    except Exception as exc:
        logger.warning("Formula extraction failed: %s", exc)
    return None


# ── System prompt ─────────────────────────────────────────────────────────────

PROFESSOR_SYSTEM_PROMPT_WITH_TOOLS = """\
You are an encouraging, expert machine learning professor guiding a student through a paper or reading list.

You have access to a tool to run formal math computations:
- query_wolfram(expression: str): Evaluates mathematical formulas, algebra, calculus, or arithmetic. Returns exact results.

If the student asks you to compute something, derive a formula, or if you need to double-check mathematical steps to prevent hallucinating math, you MUST call this tool.
To call the tool, output EXACTLY this tag inside your response, then stop writing:
<tool_call>
{{
  "tool": "query_wolfram",
  "expression": "your math expression here"
}}
</tool_call>

Once you receive the tool response, you will write your final answer. If no math verification is needed, reply normally.

---
CITATION DISCIPLINE (CRITICAL):
You MUST tag every factual claim, sentence, or definition with a citation marker referencing the Sources Context below.
- Format: `[[cite:N]]` where N is the citation index integer from the Sources Context below.
- E.g., "Scaled dot-product attention computes query-key similarity [[cite:1]]."
- If a sentence is your own explanation or is NOT directly backed by the Sources Context, you MUST append `[[cite:none]]` at the end of that sentence.
- Every single sentence must end with a citation marker: either `[[cite:N]]` or `[[cite:none]]`.

Your final reply MUST be a JSON object inside <answer> tags:
<answer>
{{
  "response": "Your structured, pedagogical reply here. You can use markdown. Ensure every sentence has a [[cite:N]] or [[cite:none]] tag.",
  "confidence_signal": null | {{
    "concept": "concept_name",
    "signal_type": "understood" | "confused" | "already_knew",
    "detected_from": "brief quote from student message"
  }}
}}
</answer>

Student Context:
- Known concepts (confidence >= 0.6): {known_concepts}
- Gap concepts (confidence < 0.6): {gap_concepts}

Paper/Topic Context:
{paper_context}

Sources Context:
{sources_context}

{wolfram_precheck}
"""


def _post_process_citations(text: str) -> str:
    """Ensure every sentence has an inline citation tag or [[cite:none]] fallback."""
    if not text:
        return text
    # Split text into sentences, keeping formatting. 
    # Match sentences ending with punctuation followed by whitespace/end of line.
    sentences = re.split(r'(?<=[.!?])\s+', text)
    processed = []
    for s in sentences:
        if not s.strip():
            processed.append(s)
            continue
        # Skip headers, lists, code block lines, or very short fragments
        if (s.strip().startswith("#") or 
            s.strip().startswith("- ") or 
            s.strip().startswith("* ") or
            "```" in s or 
            len(s.strip()) < 15):
            processed.append(s)
            continue
        
        if "[[cite:" not in s:
            # Append [[cite:none]] before the ending punctuation if possible
            if s.endswith(".") or s.endswith("!") or s.endswith("?"):
                processed.append(s[:-1] + " [[cite:none]]" + s[-1])
            else:
                processed.append(s + " [[cite:none]]")
        else:
            processed.append(s)
    return " ".join(processed)


# ── Main turn function ────────────────────────────────────────────────────────

async def run_professor_turn(
    message: str,
    turns: list[dict],
    known_concepts: list[str],
    gap_concepts: list[str],
    paper_context: str,
    paper_id: str,
    session_id: str | None = None,
    deep_study_mode: bool = False,
) -> dict:
    """
    Executes a single chat turn.

    Phase 4 additions:
      1. Proactively detect math questions before calling the LLM.
      2. If math detected: extract the relevant formula from paper chunks,
         run Wolfram verification (or full step-by-step if deep_study_mode=True), 
         and inject the result into the system prompt.
      3. Return verified_by_wolfram flag so the frontend can badge the response.

    Returns:
        {
          "response": str,
          "confidence_signal": dict | None,
          "verified_by_wolfram": bool,
        }
    """
    logger.info("Professor agent processing turn (message len=%d, deep_study=%s)...", len(message or ""), deep_study_mode)

    verified_by_wolfram = False
    wolfram_precheck_block = ""

    # ── Phase 4: Proactive Wolfram pre-routing ────────────────────────────────
    if message and _is_math_question(message):
        logger.info("Math question detected — running proactive Wolfram pre-check.")
        formula = await _extract_formula_from_context(message, paper_context)
        if formula:
            if deep_study_mode:
                logger.info("Deep Study Mode: fetching full step-by-step pods for formula: %s", formula)
                step_data = await wolfram_client.get_step_by_step(formula)
                if step_data and step_data.get("pods"):
                    verified_by_wolfram = True
                    formatted_steps = []
                    for pod in step_data["pods"]:
                        title = pod.get("title", "")
                        subpods = pod.get("subpods", [])
                        texts = [sp.get("plaintext", "") for sp in subpods if sp.get("plaintext")]
                        if texts:
                            formatted_steps.append(f"--- {title} ---\n" + "\n".join(texts))
                    
                    wolfram_res = "\n\n".join(formatted_steps)
                    wolfram_precheck_block = (
                        f"\n[Deep Study Mode: Verified by Wolfram|Alpha Full Results API]\n"
                        f"Formula extracted from paper: {formula}\n"
                        f"Wolfram Step-by-Step Result:\n{wolfram_res}\n"
                        f"Use this step-by-step breakdown directly in your explanation.\n"
                    )
            else:
                wolfram_res = await wolfram_client.verify_math(formula)
                if wolfram_res:
                    verified_by_wolfram = True
                    wolfram_precheck_block = (
                        f"\n[Pre-verified by Wolfram|Alpha LLM API]\n"
                        f"Formula extracted from paper: {formula}\n"
                        f"Wolfram result: {wolfram_res}\n"
                        f"Use this verified result in your explanation — do not contradict it.\n"
                    )
                    logger.info(
                        "Wolfram pre-check succeeded. Formula: %s → Result: %s",
                        formula[:60],
                        wolfram_res[:60],
                    )

    # ── Fetch registered citations ────────────────────────────────────────────
    citations = await citation_registry.get_citations(paper_id, session_id)
    sources_str = ""
    for c in citations:
        sources_str += f"[{c['citation_index']}] {c['source_type']}: {c['title']} ({c['year'] or 'N/A'})\n"
    if not sources_str:
        sources_str = "No external citations registered yet."

    # ── Format system prompt ──────────────────────────────────────────────────
    system_prompt = PROFESSOR_SYSTEM_PROMPT_WITH_TOOLS.format(
        known_concepts=json.dumps(known_concepts),
        gap_concepts=json.dumps(gap_concepts),
        paper_context=paper_context,
        sources_context=sources_str,
        wolfram_precheck=wolfram_precheck_block,
    )

    # ── Build history payload ─────────────────────────────────────────────────
    history_str = ""
    for turn in turns[-4:]:  # Keep last 4 turns for context to save tokens
        role = "Student" if turn["role"] == "user" else "Professor"
        content = turn["content"]
        # If response was JSON, extract the text part for readable chat history
        if isinstance(content, str) and (content.startswith("{") or "<answer>" in content):
            try:
                parsed = extract_json(content)
                content = parsed.get("response", content)
            except Exception:
                pass

        # Truncate extremely long past turns
        if isinstance(content, str) and len(content) > 500:
            content = content[:500] + "... [truncated]"

        history_str += f"{role}: {content}\n"

    prompt = f"{history_str}Student: {message}\nProfessor:"

    # ── Tool execution loop (max 2 iterations) ────────────────────────────────
    current_prompt = prompt
    for i in range(2):
        raw_response = await call_llm(
            prompt=current_prompt,
            system=system_prompt,
            temperature=0.6,
            use_reasoning=False,  # Keep response fast
        )

        # Check for reactive Wolfram tool call from LLM
        if "<tool_call>" in raw_response:
            try:
                start = raw_response.index("<tool_call>") + len("<tool_call>")
                end = raw_response.index("</tool_call>")
                tool_data = json.loads(raw_response[start:end].strip())

                if tool_data.get("tool") == "query_wolfram":
                    expr = tool_data.get("expression")
                    logger.info("LLM-triggered Wolfram tool call for: %s", expr)
                    wolfram_res = await wolfram_client.verify_math(expr)
                    if wolfram_res:
                        verified_by_wolfram = True
                    tool_result = wolfram_res or "Wolfram computation returned no results."
                    current_prompt += (
                        f"\n[Tool Call: query_wolfram({expr}) → Result: {tool_result}]\nProfessor:"
                    )
                    continue
            except Exception as exc:
                logger.error("Failed to parse/run Wolfram tool call: %s", exc)
                current_prompt += "\n[Tool Call failed]\nProfessor:"
                continue

        # Parse final answer
        try:
            result = extract_json(raw_response)
            result["verified_by_wolfram"] = verified_by_wolfram
            if "response" in result:
                result["response"] = _post_process_citations(result["response"])
            return result
        except Exception as exc:
            logger.error("Failed parsing professor final response: %s", exc)
            return {
                "response": _post_process_citations(
                    "I had trouble generating my structured response. Let me try again: "
                    + raw_response
                ),
                "confidence_signal": None,
                "verified_by_wolfram": verified_by_wolfram,
            }

    # Fallback return
    return {
        "response": "Could not complete mathematical computation. Please try rephrasing.",
        "confidence_signal": None,
        "verified_by_wolfram": False,
    }

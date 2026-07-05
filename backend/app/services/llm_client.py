# -*- coding: utf-8 -*-
"""
app/services/llm_client.py

OpenRouter async LLM client with:
  - Default model: deepseek/deepseek-v4-flash
  - Reasoning support (selective CoT)
  - JSON extraction with markdown-fence stripping and trailing-comma repair
  - Rate-limit budget tracking visible in logs
  - Temperature 0.2 for extraction tasks, caller can override for chat

This is the ONLY place in the codebase that makes OpenRouter calls.
Every other module that needs an LLM result calls call_llm() from here.
"""

import asyncio
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.utils.cache_manager import CACHE_DIR

logger = logging.getLogger(__name__)

# Primary model first.
MODEL_CHAIN = [
    "deepseek/deepseek-v4-flash",
]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── Daily rate tracker ────────────────────────────────────────────────────────
_TRACKER_FILE = CACHE_DIR / "rate_tracker.json"


def _load_tracker() -> dict:
    today = date.today().isoformat()
    if _TRACKER_FILE.exists():
        try:
            data = json.loads(_TRACKER_FILE.read_text())
            if data.get("date") == today:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"date": today, "used": 0}


def _save_tracker(data: dict) -> None:
    try:
        _TRACKER_FILE.write_text(json.dumps(data))
    except OSError:
        pass


def _record_llm_call() -> int:
    """Increment counter and return remaining budget."""
    data = _load_tracker()
    data["used"] += 1
    _save_tracker(data)
    remaining = 500 - data["used"]  # Expanded budget for v2 processing
    logger.debug("OpenRouter budget: %d used today, %d remaining", data["used"], remaining)
    return remaining


# ── JSON extraction helpers ───────────────────────────────────────────────────

def extract_json(raw: str) -> dict:
    """
    Robustly extract a JSON object from a model response.
    """
    raw = raw.strip()

    # Defensive stopgap: replace doubled braces with single braces
    raw = raw.replace('{{', '{').replace('}}', '}')

    # Step 1: strip markdown code fences
    if raw.startswith("```"):
        parts = raw.split("```")
        inner = parts[1] if len(parts) > 1 else raw
        if inner.lower().startswith("json"):
            inner = inner[4:]
        raw = inner.strip()

    # Step 2: strip <thinking> tags and handle <answer> XML tags if they exist
    if "<thinking>" in raw and "</thinking>" in raw:
        start_think = raw.index("<thinking>")
        end_think = raw.index("</thinking>") + len("</thinking>")
        raw = raw[:start_think] + raw[end_think:]

    if "<answer>" in raw and "</answer>" in raw:
        start = raw.index("<answer>") + len("<answer>")
        end = raw.index("</answer>")
        raw = raw[start:end].strip()

    # Step 3: grab the outermost { ... } block
    brace_start = raw.find("{")
    brace_end = raw.rfind("}")
    if brace_start == -1 or brace_end == -1:
        raise ValueError(f"No JSON object found in model output: {raw[:200]!r}")
    candidate = raw[brace_start : brace_end + 1]

    # Step 4: attempt direct parse
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Step 5: repair trailing commas
    repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
    return json.loads(repaired)


def _normalize_text(text: str) -> str:
    # lowercase, strip hyphens at line breaks, collapse whitespace
    text = text.lower()
    text = re.sub(r"-\n\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def validate_evidence_quotes(concepts: list[dict], source_text: str) -> list[dict]:
    """Validate evidence quotes using fuzzy matching. Allow semantic deductions if not found."""
    from rapidfuzz import fuzz
    
    validated = []
    source_norm = _normalize_text(source_text)
    
    for c in concepts:
        quote = c.get("evidence_quote", "")
        # If no quote was provided, treat it as a valid semantic deduction
        if not quote:
            c["evidence_type"] = "semantic_deduction"
            validated.append(c)
            continue
            
        quote_norm = _normalize_text(quote)
        words = quote_norm.split()
        
        is_valid = False
        
        # If quote is very short, require it to be an exact substring
        if len(words) < 6:
            if quote_norm in source_norm:
                is_valid = True
            else:
                # We can also check if the partial ratio is extremely high for slight typos
                if fuzz.partial_ratio(quote_norm, source_norm) >= 90:
                    is_valid = True
        else:
            # Fuzzy match for longer quotes
            partial_score = fuzz.partial_ratio(quote_norm, source_norm)
            if partial_score >= 80:  # Loosened from 85 to 80
                is_valid = True
                
        if is_valid:
            c["evidence_type"] = "explicit_quote"
            validated.append(c)
        else:
            # Fallback to semantic deduction instead of dropping the concept entirely
            logger.info("Preserving concept '%s' as semantic deduction (hallucinated quote %r)", c["name"], quote)
            c["evidence_type"] = "semantic_deduction"
            c["evidence_quote"] = "Derived from semantic context (explicit quote could not be exactly verified)."
            validated.append(c)
            
    return validated


# ── Main async LLM caller ─────────────────────────────────────────────────────

async def call_llm(
    prompt: str,
    system: str = "",
    temperature: float = 0.2,
    use_reasoning: bool = False,
    max_retries_per_model: int = 2,
    response_format: dict = None,
) -> str:
    """
    Send a prompt to OpenRouter using the fallback chain.
    """
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://papermind.dev",
        "X-Title": "PaperMind",
    }

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=60.0) as client:
        for model in MODEL_CHAIN:
            for attempt in range(max_retries_per_model):
                try:
                    payload = {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                    }
                    if response_format:
                        payload["response_format"] = response_format
                    # Enable reasoning only if model is deepseek-v4-flash and use_reasoning is True
                    if use_reasoning and "deepseek-v4" in model:
                        payload["reasoning"] = {"enabled": True}

                    response = await client.post(
                        OPENROUTER_URL,
                        headers=headers,
                        json=payload,
                    )

                    if response.status_code == 429:
                        wait = 2 ** attempt
                        logger.warning("Rate limited on %s (attempt %d). Waiting %ds.", model, attempt + 1, wait)
                        await asyncio.sleep(wait)
                        continue

                    response.raise_for_status()
                    _record_llm_call()
                    return response.json()["choices"][0]["message"]["content"]

                except (httpx.HTTPError, KeyError, IndexError) as exc:
                    logger.warning("LLM call failed on %s attempt %d: %s", model, attempt + 1, exc)
                    continue

            logger.warning("Model %s exhausted all retries, trying next in chain.", model)

    raise RuntimeError(
        "All models in the OpenRouter fallback chain failed. "
        "Check your API key and network connection."
    )


async def call_llm_for_json(
    prompt: str,
    system: str = "",
    temperature: float = 0.2,
    use_reasoning: bool = False,
    max_retries_per_model: int = 2,
) -> dict:
    """
    Wrapper around call_llm that parses the response as JSON.
    """
    for attempt in range(2):
        raw = await call_llm(
            prompt,
            system=system,
            temperature=temperature,
            use_reasoning=use_reasoning,
            max_retries_per_model=max_retries_per_model,
            response_format={"type": "json_object"}
        )
        try:
            return extract_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("JSON extraction failed on attempt %d: %s. Raw: %r", attempt + 1, exc, raw[:300])
            if attempt == 0:
                continue
            raise ValueError(f"Could not extract valid JSON after 2 attempts. Last raw output: {raw[:500]!r}") from exc

    raise RuntimeError("JSON extraction loop exited unexpectedly")

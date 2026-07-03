"""
app/services/llm_client.py

OpenRouter async LLM client with:
  - Ordered fallback model chain (plan Part 1, Section 3.1)
  - JSON extraction with markdown-fence stripping and trailing-comma repair
    (plan Part 1, Section 3.2)
  - Rate-limit budget tracking visible in logs
  - Temperature 0.2 for extraction tasks, caller can override for chat

This is the ONLY place in the codebase that makes OpenRouter calls.
Every other module that needs an LLM result calls call_llm() from here.
"""

import json
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.utils.cache_manager import CACHE_DIR

logger = logging.getLogger(__name__)

# ── Fallback model chain ──────────────────────────────────────────────────────
# Primary first. On a 429 or failed JSON parse, move to the next.
# Verify these slugs against https://openrouter.ai/models before hardcoding.
MODEL_CHAIN = [
    "deepseek/deepseek-chat:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
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
    remaining = 200 - data["used"]
    logger.debug("OpenRouter budget: %d used today, %d remaining", data["used"], remaining)
    return remaining


# ── JSON extraction helpers ───────────────────────────────────────────────────

def extract_json(raw: str) -> dict:
    """
    Robustly extract a JSON object from a model response.

    Free models sometimes:
      1. Wrap the JSON in markdown code fences (```json ... ```)
      2. Add a preamble sentence before the JSON
      3. Add trailing commas (invalid JSON but common output)

    We handle all three. If this still fails, the caller should retry
    with a fresh model generation rather than trying to parse harder.
    """
    raw = raw.strip()

    # Step 1: strip markdown code fences
    if raw.startswith("```"):
        parts = raw.split("```")
        # parts[1] is the content between the first pair of fences
        inner = parts[1] if len(parts) > 1 else raw
        if inner.lower().startswith("json"):
            inner = inner[4:]
        raw = inner.strip()

    # Step 2: also handle <output> XML tags the prompts request
    if "<output>" in raw and "</output>" in raw:
        start = raw.index("<output>") + len("<output>")
        end = raw.index("</output>")
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

    # Step 5: repair trailing commas — the most common free-model JSON failure
    repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
    return json.loads(repaired)  # let this raise naturally if still broken


# ── Main async LLM caller ─────────────────────────────────────────────────────

async def call_llm(
    prompt: str,
    system: str = "",
    temperature: float = 0.2,
    max_retries_per_model: int = 2,
) -> str:
    """
    Send a prompt to OpenRouter using the fallback chain.

    Args:
        prompt: The user message.
        system: Optional system prompt. Pass "" to omit.
        temperature: 0.2 for extraction/classification; 0.6–0.7 for chat.
        max_retries_per_model: Retry count before advancing to the next model.

    Returns:
        Raw text content from the model.

    Raises:
        RuntimeError: If every model in the chain is exhausted.
    """
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://papermind.dev",  # OpenRouter attribution
        "X-Title": "PaperMind",
    }

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=45.0) as client:
        for model in MODEL_CHAIN:
            for attempt in range(max_retries_per_model):
                try:
                    response = await client.post(
                        OPENROUTER_URL,
                        headers=headers,
                        json={
                            "model": model,
                            "messages": messages,
                            "temperature": temperature,
                        },
                    )

                    if response.status_code == 429:
                        wait = 2 ** attempt
                        logger.warning("Rate limited on %s (attempt %d). Waiting %ds.", model, attempt + 1, wait)
                        time.sleep(wait)
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
    max_retries_per_model: int = 2,
) -> dict:
    """
    Wrapper around call_llm that parses the response as JSON.
    Retries with a fresh generation if JSON extraction fails.
    """
    for attempt in range(2):
        raw = await call_llm(prompt, system=system, temperature=temperature, max_retries_per_model=max_retries_per_model)
        try:
            return extract_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("JSON extraction failed on attempt %d: %s. Raw: %r", attempt + 1, exc, raw[:300])
            if attempt == 0:
                continue  # retry once with a fresh generation
            raise ValueError(f"Could not extract valid JSON after 2 attempts. Last raw output: {raw[:500]!r}") from exc

    # unreachable, but satisfies type checkers
    raise RuntimeError("JSON extraction loop exited unexpectedly")

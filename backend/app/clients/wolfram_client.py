# -*- coding: utf-8 -*-
"""
app/clients/wolfram_client.py

Wolfram|Alpha API client for math computations and verification.
Provides:
  1. Live verification (via LLM API /v1/llm-api)
  2. Full Step-by-Step pods (via Full Results API /v2/query)
Graces out if WOLFRAM_APP_ID is not configured.
"""

import logging
import httpx
from app.core.config import get_settings
from app.services.external_cache import get_cached, set_cached

logger = logging.getLogger(__name__)

async def verify_math(expression: str) -> str | None:
    """
    Query Wolfram|Alpha LLM API to get a plain-text evaluation of a math expression.
    Useful for validating student statements or checking formula correctness.
    """
    settings = get_settings()
    appid = settings.wolfram_app_id
    if not appid:
        logger.warning("WOLFRAM_APP_ID is not configured. Math verification skipped.")
        return None

    # Check cache first
    cache_key = f"wolfram:llm:{expression}"
    cached = await get_cached(cache_key)
    if cached:
        return cached.get("result")

    url = "https://www.wolframalpha.com/api/v1/llm-api"
    headers = {
        "Authorization": f"Bearer {appid}"
    }
    params = {
        "input": expression,
        "maxchars": 1500
    }
    
    async def _fetch(current_expr: str, attempt: int = 1) -> str | None:
        params["input"] = current_expr
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, headers=headers, params=params, timeout=15.0)
                if response.status_code == 200:
                    result = response.text.strip()
                    await set_cached(cache_key, "wolfram", {"result": result})
                    return result
                elif response.status_code == 501:
                    logger.debug("Wolfram LLM API could not understand query: %s", current_expr)
                    if attempt == 1:
                        # Attempt to parse "You could instead try: X"
                        import re
                        match = re.search(r"You could instead try:\s*(.+)", response.text)
                        if match:
                            suggestion = match.group(1).strip()
                            logger.info("Retrying Wolfram with suggestion: %s", suggestion)
                            return await _fetch(suggestion, attempt=2)
                    return None
                else:
                    logger.error("Wolfram LLM API returned status %d: %s", response.status_code, response.text[:200])
        except Exception as exc:
            logger.error("Wolfram LLM API call failed: %r", exc)
        return None

    return await _fetch(expression)

async def get_step_by_step(expression: str) -> dict | None:
    """
    Query Wolfram|Alpha Full Results API for step-by-step explanation pods.
    Useful for offline derivation enrichment.
    """
    settings = get_settings()
    appid = settings.wolfram_app_id
    if not appid:
        logger.warning("WOLFRAM_APP_ID is not configured. Step-by-step derivation skipped.")
        return None

    cache_key = f"wolfram:steps:{expression}"
    cached = await get_cached(cache_key)
    if cached:
        return cached

    url = "https://api.wolframalpha.com/v2/query"
    params = {
        "input": expression,
        "appid": appid,
        "podstate": "Step-by-step solution",
        "format": "plaintext,mathml",
        "output": "json"
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, params=params, timeout=15.0)
            if response.status_code == 200:
                data = response.json()
                # Parse pods to extract step-by-step explanation
                query_result = data.get("queryresult", {})
                if query_result.get("success"):
                    # Cache response
                    await set_cached(cache_key, "wolfram", query_result)
                    return query_result
    except Exception as exc:
        logger.error("Wolfram Full Results API call failed: %s", exc)
    return None

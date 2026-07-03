"""
smoke_test.py

Day-1 verification script — run this before building anything else.
Confirms four things against your actual Cognee install and credentials:
  1. What SearchType enum values are available
  2. What remember() returns (does it have a data_id field?)
  3. What INSIGHTS results look like structurally
  4. That dataset-level forget() actually removes data

Run from the backend/ directory:
  python smoke_test.py

Expected output:
  - A list of SearchType names
  - remember() return value structure
  - INSIGHTS query result (may be empty on first run if not yet cognified)
  - "After forget:" should show empty or reduced results

From plan Part 3 Section 6.
"""

import asyncio
import os
import sys

# Load .env before anything else
from dotenv import load_dotenv
load_dotenv()

import cognee
from cognee import search, SearchType


async def main() -> None:
    print("\n" + "=" * 60)
    print("PaperMind — Cognee Smoke Test")
    print("=" * 60)

    # ── Step 0: configure Cognee ──────────────────────────────────────────────
    cognee_api_key = os.getenv("COGNEE_API_KEY", "")
    cognee_service_url = os.getenv("COGNEE_SERVICE_URL", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

    if cognee_api_key and cognee_service_url:
        print(f"\n[Mode] Cognee Cloud → {cognee_service_url}")
        try:
            await cognee.serve(url=cognee_service_url, api_key=cognee_api_key)
            print("    cognee.serve() succeeded — connected to Cloud tenant")
        except Exception as e:
            print(f"    cognee.serve() failed: {e}")
            print("    Falling back to local mode for this test run.")
    else:
        print("\n[Mode] Cognee Local (COGNEE_SERVICE_URL or COGNEE_API_KEY not set)")
        if openrouter_key:
            # In local mode, Cognee needs an LLM for its cognify() pipeline.
            # Keys use the llm_* prefix as documented at docs.cognee.ai/python-api/config
            cognee.config.set_llm_config({
                "llm_provider": "openai",
                "llm_model": os.getenv("LLM_MODEL", "deepseek/deepseek-chat:free"),
                "llm_api_key": openrouter_key,
                "llm_endpoint": "https://openrouter.ai/api/v1",
            })
            cognee.config.set_embedding_config({
                "embedding_provider": "fastembed",
                "embedding_model": "BAAI/bge-small-en-v1.5",
            })
            print("    Local LLM configured via OpenRouter + fastembed embeddings")

    # ── Step 1: available SearchType values ──────────────────────────────────
    print("\n[1] Available SearchType values:")
    search_types = [s.name for s in SearchType]
    for st in search_types:
        print(f"    {st}")

    # ── Step 2: clean slate ───────────────────────────────────────────────────
    print("\n[2] Clearing smoke_test dataset...")
    try:
        await cognee.forget(dataset="smoke_test_paper_concepts")
        print("    forget() succeeded")
    except Exception as e:
        print(f"    forget() raised (may not exist yet): {e}")

    # ── Step 3: remember() ────────────────────────────────────────────────────
    print("\n[3] Calling remember()...")
    test_text = (
        "The concept 'multi-head attention' requires prior understanding of "
        "'scaled dot-product attention'. Scaled dot-product attention is defined "
        "as a method of computing attention weights using query, key, and value matrices."
    )
    try:
        result = await cognee.remember(test_text, dataset_name="smoke_test_paper_concepts")
        print(f"    remember() returned: {type(result).__name__}")
        print(f"    Has data_id? {hasattr(result, 'data_id')}")
        print(f"    Return value: {result}")
    except Exception as e:
        print(f"    remember() failed: {e}")
        return

    # ── Step 4: INSIGHTS search ───────────────────────────────────────────────
    print("\n[4] INSIGHTS search...")
    try:
        insights = await search(
            query_text="multi-head attention prerequisites",
            query_type=SearchType.INSIGHTS,
            datasets=["smoke_test_paper_concepts"],
        )
        print(f"    Result type: {type(insights).__name__}")
        print(f"    Result: {str(insights)[:300]}")
    except Exception as e:
        print(f"    INSIGHTS search failed: {e}")

    # ── Step 5: GRAPH_COMPLETION search ──────────────────────────────────────
    print("\n[5] GRAPH_COMPLETION search...")
    try:
        answer = await search(
            query_text="what does multi-head attention require?",
            query_type=SearchType.GRAPH_COMPLETION,
            datasets=["smoke_test_paper_concepts"],
        )
        print(f"    Answer: {str(answer)[:300]}")
    except Exception as e:
        print(f"    GRAPH_COMPLETION search failed: {e}")

    # ── Step 6: verify forget() precision ────────────────────────────────────
    print("\n[6] Testing dataset-level forget() precision...")
    try:
        await cognee.forget(dataset="smoke_test_paper_concepts")
        post_forget = await search(
            query_text="multi-head attention",
            query_type=SearchType.CHUNKS,
            datasets=["smoke_test_paper_concepts"],
        )
        print(f"    After forget(), result (should be empty/none): {str(post_forget)[:200]}")
    except Exception as e:
        print(f"    Post-forget search raised: {e}")

    print("\n" + "=" * 60)
    print("Smoke test complete. Review the output above before building further.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

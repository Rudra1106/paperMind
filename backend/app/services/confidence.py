"""
app/services/confidence.py

Manages user concept confidence scores in Cognee.

Architecture (plan Part 3 Section 2, corrected from Part 2 Section 7.5):
  Each concept gets its own tiny Cognee dataset named:
    "user_knowledge__<canonical_name>"

  This lets us use forget(dataset=...) for precise per-concept deletion
  without tracking data_ids or risking the standalone-DataPoint
  dataset-association gotcha described in Part 3 Section 2.

  Trade-off: we may accumulate 50-150 small datasets over time.
  To avoid making 50+ Cognee calls on every /knowledge-graph request,
  we maintain a local JSON confidence index (via cache_manager) that
  mirrors the current state. Cognee is the source of truth; the index
  is a read cache for fast queries.

Locking (plan Part 2 Section 7.5):
  A per-concept asyncio.Lock ensures the forget() → remember() cycle
  is atomic within a single process. This prevents lost updates when
  the chat endpoint and the improve() consolidation fire concurrently.
  The lock is keyed per concept — updates to different concepts still
  run concurrently.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import date

import cognee

from app.utils.canonical import canonical, user_knowledge_dataset_name
from app.utils.cache_manager import JSONCache, CACHE_DIR

logger = logging.getLogger(__name__)

# Per-concept async locks — keyed by canonical name.
# defaultdict(asyncio.Lock) creates a new Lock the first time a key is accessed.
_concept_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# Local confidence index — fast reads without hitting Cognee on every request.
# Format: { "canonical_name": float_confidence }
_confidence_index = JSONCache("confidence_index.json")


def _format_knowledge_ingestion(concept_name: str, confidence: float, source: str) -> str:
    """
    Structured text that Cognee's internal extractor can parse consistently.
    Deliberately terse — we're using Cognee here as a queryable store,
    not for relationship extraction (confidence scores have no graph edges).
    """
    today = date.today().isoformat()
    return (
        f"Concept: {concept_name}. "
        f"Confidence: {confidence:.2f}. "
        f"Last updated: {today}. "
        f"Source: {source}."
    )


async def get_current_confidence(canonical_name: str) -> float:
    """Read the current confidence from the local index (fast path)."""
    cached = _confidence_index.get(canonical_name)
    if cached is not None:
        return float(cached)
    return 0.0


async def update_confidence(
    concept_name: str,
    delta: float | None = None,
    set_value: float | None = None,
    source: str = "chat",
) -> float:
    """
    Update the confidence score for a concept, atomically.

    Exactly one of delta or set_value must be provided:
      - delta: add this amount to the current score (clamped to [0.0, 1.0])
      - set_value: set the score to this exact value

    The forget() → remember() sequence is protected by a per-concept lock
    to prevent race conditions between concurrent confidence updates.
    """
    if delta is None and set_value is None:
        raise ValueError("update_confidence: provide either delta or set_value")

    cname = canonical(concept_name)
    dataset = user_knowledge_dataset_name(cname)

    async with _concept_locks[cname]:
        current = await get_current_confidence(cname)

        if set_value is not None:
            new_value = max(0.0, min(1.0, set_value))
        else:
            new_value = max(0.0, min(1.0, current + delta))  # type: ignore[operator]

        # Surgical delete of this concept's dataset, then re-ingest with new score
        try:
            await cognee.forget(dataset=dataset)
        except Exception as exc:
            logger.debug("forget() for %s raised (may not exist yet): %s", dataset, exc)

        ingestion_text = _format_knowledge_ingestion(cname, new_value, source)
        await cognee.remember(ingestion_text, dataset_name=dataset)

        # Update local index for fast reads
        _confidence_index.set(cname, new_value)
        logger.info("Confidence updated: %s %.2f → %.2f (via %s)", cname, current, new_value, source)

    return new_value


# ── The four confidence update triggers (plan Part 2 Section 7.6) ─────────────

async def handle_confidence_signal(signal: dict) -> float | None:
    """
    Apply a confidence delta based on a signal detected from chat.

    signal = {"concept": "...", "signal_type": "understood"|"confused"|"already_knew", ...}
    """
    mapping = {
        "understood": (0.3, None),
        "confused": (-0.1, None),
        "already_knew": (None, 0.9),
    }
    signal_type = signal.get("signal_type")
    if signal_type not in mapping:
        logger.warning("Unknown signal_type: %r", signal_type)
        return None

    delta, set_val = mapping[signal_type]
    return await update_confidence(
        signal["concept"],
        delta=delta,
        set_value=set_val,
        source="chat",
    )


async def handle_followup_engagement(concept_name: str) -> float:
    """Small bump when a learner asks a follow-up question about a concept."""
    return await update_confidence(concept_name, delta=0.1, source="chat")


async def handle_cross_paper_reinforcement(concept_name: str) -> float:
    """Bump when the same concept appears in a newly uploaded paper."""
    return await update_confidence(concept_name, delta=0.15, source="paper")


async def manual_update(concept_name: str, action: str) -> float:
    """
    Handle explicit manual updates from the /concept/update endpoint.
    action: "understood" | "confused" | "mastered"
    """
    mapping = {
        "understood": (0.3, None),
        "confused": (-0.1, None),
        "mastered": (None, 1.0),
    }
    if action not in mapping:
        raise ValueError(f"Unknown action: {action!r}. Expected: understood, confused, mastered")

    delta, set_val = mapping[action]
    return await update_confidence(concept_name, delta=delta, set_value=set_val, source="manual")


def get_all_confidence_scores() -> dict[str, float]:
    """Return the full local confidence index as a dict."""
    return dict(_confidence_index._data)


async def mark_concepts_from_paper(concepts: list[dict]) -> None:
    """
    When a paper is uploaded, check which concepts the user already knows
    (confidence > 0) and apply cross-paper reinforcement to them.
    Called from the background upload job.
    """
    for concept in concepts:
        cname = concept["canonical_name"]
        current = await get_current_confidence(cname)
        if current > 0.0:
            await handle_cross_paper_reinforcement(cname)

# -*- coding: utf-8 -*-
"""
app/services/confidence.py

Manages user concept confidence scores in Postgres via Supabase.

Architecture Upgrade (Phase 2):
  Moved from Cognee per-concept datasets to a single Postgres table (`concept_confidence`).
  This eliminates the 50-150 dataset explosion per user and removes the need for local
  `asyncio.Lock` since Postgres handles concurrent UPSERTs safely.
"""

import logging
from datetime import date
from app.core.supabase_client import get_supabase
from app.utils.canonical import canonical

logger = logging.getLogger(__name__)


async def get_current_confidence(user_id: str, canonical_name: str) -> float:
    """Read the current confidence from Postgres."""
    supabase = get_supabase()
    response = supabase.table("concept_confidence").select("confidence").eq("user_id", user_id).eq("canonical_name", canonical_name).execute()
    if response.data:
        return float(response.data[0]["confidence"])
    return 0.0


async def update_confidence(
    user_id: str,
    concept_name: str,
    delta: float | None = None,
    set_value: float | None = None,
    source: str = "chat",
) -> float:
    """
    Update the confidence score for a concept.
    Exactly one of delta or set_value must be provided.
    """
    if delta is None and set_value is None:
        raise ValueError("update_confidence: provide either delta or set_value")

    cname = canonical(concept_name)
    current = await get_current_confidence(user_id, cname)

    if set_value is not None:
        new_value = max(0.0, min(1.0, set_value))
    else:
        new_value = max(0.0, min(1.0, current + delta))  # type: ignore[operator]

    supabase = get_supabase()
    
    # Postgres UPSERT
    supabase.table("concept_confidence").upsert({
        "user_id": user_id,
        "canonical_name": cname,
        "display_name": concept_name,
        "confidence": new_value,
        "last_source": source
    }, on_conflict="user_id,canonical_name").execute()

    logger.info("Confidence updated: %s %.2f → %.2f (via %s)", cname, current, new_value, source)
    return new_value


# ── The four confidence update triggers (plan Part 2 Section 7.6) ─────────────

async def handle_confidence_signal(user_id: str, signal: dict) -> float | None:
    """
    Apply a confidence delta based on a signal detected from chat.
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
        user_id,
        signal["concept"],
        delta=delta,
        set_value=set_val,
        source="chat",
    )


async def handle_followup_engagement(user_id: str, concept_name: str) -> float:
    """Small bump when a learner asks a follow-up question about a concept."""
    return await update_confidence(user_id, concept_name, delta=0.1, source="chat")


async def handle_cross_paper_reinforcement(user_id: str, concept_name: str) -> float:
    """Bump when the same concept appears in a newly uploaded paper."""
    return await update_confidence(user_id, concept_name, delta=0.15, source="paper")


async def manual_update(user_id: str, concept_name: str, action: str) -> float:
    """
    Handle explicit manual updates from the /concept/update endpoint.
    """
    mapping = {
        "understood": (0.3, None),
        "confused": (-0.1, None),
        "mastered": (None, 1.0),
    }
    if action not in mapping:
        raise ValueError(f"Unknown action: {action!r}. Expected: understood, confused, mastered")

    delta, set_val = mapping[action]
    return await update_confidence(user_id, concept_name, delta=delta, set_value=set_val, source="manual")


async def get_all_confidence_scores(user_id: str) -> dict[str, float]:
    """Return the full confidence index as a dict for a given user."""
    supabase = get_supabase()
    response = supabase.table("concept_confidence").select("canonical_name, confidence").eq("user_id", user_id).execute()
    return {row["canonical_name"]: float(row["confidence"]) for row in response.data}


async def mark_concepts_from_paper(user_id: str, concepts: list[dict]) -> None:
    """
    When a paper is uploaded, initialize all concepts in the user's knowledge base
    with 0.0 confidence if they don't exist. If they do exist and confidence > 0,
    apply cross-paper reinforcement.
    """
    supabase = get_supabase()
    
    for concept in concepts:
        cname = concept["canonical_name"]
        dname = concept.get("display_name") or concept["name"]
        
        current = await get_current_confidence(user_id, cname)
        if current > 0.0:
            # User already knows this, give a reinforcement bump
            await handle_cross_paper_reinforcement(user_id, cname)
        else:
            # Initialize with 0.0 so it appears in the knowledge base graph
            supabase.table("concept_confidence").upsert({
                "user_id": user_id,
                "canonical_name": cname,
                "display_name": dname,
                "confidence": 0.0,
                "last_source": "paper_init"
            }, on_conflict="user_id,canonical_name").execute()


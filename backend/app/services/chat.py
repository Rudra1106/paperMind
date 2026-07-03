"""
app/services/chat.py

Professor agent orchestration: context building, session management,
and the main turn loop.

Session design (plan Part 1 Section 7.1):
  - ChatSession is an in-memory dataclass for the duration of the session.
  - A JSON snapshot is written after every turn — crash-safety insurance
    against the worst demo-day failure mode (server restart mid-demo).
  - Cognee's remember(session_id=...) stores ephemeral session memory
    that improve() bridges to the permanent graph at session end.

Context building (plan Part 3 Section 1.2 / revised professor context):
  - Use SearchType.INSIGHTS for structured prerequisite edges.
  - Use SearchType.GRAPH_COMPLETION for synthesized explanation material.
  - Use SearchType.SIMILARITY for semantically close content without
    caring about graph structure.

One LLM call per turn (plan Part 1 Section 7.4):
  - The professor response and confidence signal classification are
    combined into a single structured JSON response.
  - This halves per-turn LLM cost against the 200/day budget.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import cognee

from app.prompts.professor import PROFESSOR_SYSTEM_PROMPT, PROFESSOR_USER_TURN_FORMAT
from app.services.llm_client import call_llm_for_json
from app.utils.cache_manager import CACHE_DIR

logger = logging.getLogger(__name__)

SESSIONS_DIR = CACHE_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


# ── Session data structure ────────────────────────────────────────────────────

@dataclass
class ChatSession:
    session_id: str
    paper_id: str
    user_id: str = "default"
    turns: list[dict] = field(default_factory=list)
    concepts_discussed: set[str] = field(default_factory=set)
    pending_confidence_signals: list[dict] = field(default_factory=list)


# Module-level session store — in-memory for the hackathon scope.
# Multi-user or persistent sessions would need a database or Redis.
_sessions: dict[str, ChatSession] = {}


def get_or_create_session(session_id: str, paper_id: str) -> ChatSession:
    if session_id not in _sessions:
        # Try to restore from snapshot first
        snapshot_path = SESSIONS_DIR / f"{session_id}.json"
        if snapshot_path.exists():
            try:
                data = json.loads(snapshot_path.read_text())
                session = ChatSession(
                    session_id=data["session_id"],
                    paper_id=data["paper_id"],
                    turns=data.get("turns", []),
                    concepts_discussed=set(data.get("concepts_discussed", [])),
                )
                _sessions[session_id] = session
                logger.info("Restored session %s from snapshot.", session_id)
                return session
            except (json.JSONDecodeError, KeyError, OSError):
                pass

        _sessions[session_id] = ChatSession(session_id=session_id, paper_id=paper_id)

    return _sessions[session_id]


def persist_session_snapshot(session: ChatSession) -> None:
    """Write a JSON snapshot after every turn — crash-safety insurance."""
    snapshot_path = SESSIONS_DIR / f"{session.session_id}.json"
    data = {
        "session_id": session.session_id,
        "paper_id": session.paper_id,
        "turns": session.turns[-20:],  # keep last 20 turns in snapshot
        "concepts_discussed": list(session.concepts_discussed),
    }
    try:
        snapshot_path.write_text(json.dumps(data, indent=2))
    except OSError as exc:
        logger.warning("Failed to write session snapshot: %s", exc)


# ── Cognee context retrieval ──────────────────────────────────────────────────

async def build_professor_context(paper_id: str, question: str) -> dict:
    """
    Retrieve relevant context from Cognee using explicit SearchType values.

    INSIGHTS   → structured prerequisite edges for the topological context
    GRAPH_COMPLETION → synthesized explanation from the paper's knowledge subgraph
    SIMILARITY → semantically close concept chunks without caring about structure

    We don't rely on FEELING_LUCKY auto-routing because the personalization
    value proposition depends on deliberate retrieval strategy choices.
    """
    try:
        from cognee import search, SearchType

        # Run all three searches concurrently — they're all reads, no conflict
        prereq_task = search(
            query_text=f"prerequisites for: {question}",
            query_type=SearchType.INSIGHTS,
            datasets=["paper_concepts"],
        )
        explanation_task = search(
            query_text=question,
            query_type=SearchType.GRAPH_COMPLETION,
            datasets=[f"paper_{paper_id}_fulltext", "paper_concepts"],
        )
        similar_task = search(
            query_text=question,
            query_type=SearchType.SIMILARITY,
            datasets=["paper_concepts"],
        )

        prereq_result, explanation_result, similar_result = await asyncio.gather(
            prereq_task,
            explanation_task,
            similar_task,
            return_exceptions=True,
        )

        return {
            "prereq_edges": prereq_result if not isinstance(prereq_result, Exception) else [],
            "graph_explanation": explanation_result if not isinstance(explanation_result, Exception) else "",
            "similar_chunks": similar_result if not isinstance(similar_result, Exception) else [],
        }

    except Exception as exc:
        logger.warning("Cognee context retrieval failed: %s. Proceeding without graph context.", exc)
        return {"prereq_edges": [], "graph_explanation": "", "similar_chunks": []}


def _format_context_for_prompt(context: dict) -> str:
    """Format the Cognee retrieval results into a readable prompt section."""
    parts = []

    if context.get("graph_explanation"):
        parts.append(f"From the paper's knowledge graph:\n{context['graph_explanation']}")

    if context.get("prereq_edges"):
        edges_text = str(context["prereq_edges"])[:800]  # cap length
        parts.append(f"Prerequisite relationships:\n{edges_text}")

    if context.get("similar_chunks"):
        chunks_text = str(context["similar_chunks"])[:600]
        parts.append(f"Related content:\n{chunks_text}")

    return "\n\n".join(parts) if parts else "No additional context available from the paper."


# ── Main turn loop ────────────────────────────────────────────────────────────

async def run_professor_turn(
    session: ChatSession,
    message: str,
    known_concepts: dict[str, float],
    gap_concepts: list[dict],
    context: dict,
) -> dict:
    """
    Generate the professor's response for one chat turn.

    Returns a dict with:
      - "response": the explanation text
      - "confidence_signal": dict or None
    """
    # Format conversation history for the system prompt (last 8 turns max)
    recent_turns = session.turns[-8:]
    history_text = "\n".join(
        f"{t['role'].upper()}: {t['content']}" for t in recent_turns
    )

    # Format the lists of known vs gap concepts for the system prompt
    known_list = ", ".join(k for k, v in known_concepts.items() if v >= 0.6) or "none yet"
    gap_list = ", ".join(c["canonical_name"] for c in gap_concepts[:15]) or "none identified"
    graph_context = _format_context_for_prompt(context)

    system_prompt = PROFESSOR_SYSTEM_PROMPT.format(
        known_concepts_list=known_list,
        gap_list_for_this_paper=gap_list,
        graph_context=graph_context,
        recent_turns=history_text,
    )

    user_turn = PROFESSOR_USER_TURN_FORMAT.format(learner_message=message)

    result = await call_llm_for_json(
        user_turn,
        system=system_prompt,
        temperature=0.65,  # more varied phrasing is fine for explanations
    )

    # Store the turn in Cognee's session memory for improve() later
    try:
        await cognee.remember(
            f"Learner asked: {message}\nProfessor responded: {result.get('response', '')}",
            dataset_name=f"session_{session.session_id}",
        )
    except Exception as exc:
        logger.debug("Cognee session remember failed: %s", exc)

    # Track which concepts were mentioned in this turn
    for concept in gap_concepts:
        if concept["canonical_name"].replace("_", " ") in message.lower():
            session.concepts_discussed.add(concept["canonical_name"])

    return {
        "response": result.get("response", "I encountered an issue generating a response. Please try again."),
        "confidence_signal": result.get("confidence_signal"),
    }


async def consolidate_session(session: ChatSession) -> None:
    """
    Bridge ephemeral session memory into the permanent graph at session end.
    Called explicitly from the chat endpoint when a session ends.
    """
    try:
        await cognee.improve(dataset_name="user_knowledge")
        logger.info("Session %s consolidated into permanent graph.", session.session_id)
    except Exception as exc:
        logger.warning("Session consolidation failed: %s", exc)

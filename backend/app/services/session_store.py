# -*- coding: utf-8 -*-
"""
app/services/session_store.py

Session persistence service for PaperMind chat history (ChatGPT-like sidebar).
Stores session metadata, titles, and JSON-serialized message turns in Postgres.
"""

import logging
from datetime import datetime
from app.core.supabase_client import get_supabase
from app.services.llm_client import call_llm

logger = logging.getLogger(__name__)

async def generate_session_title(first_message: str) -> str:
    """Use a quick LLM call to generate a 3-5 word title for the session."""
    prompt = (
        "Generate a brief, user-friendly 3-5 word title for a chat session starting with this question. "
        "Do NOT output quotes, formatting, or extra text. Output ONLY the title.\n\n"
        f"Question: {first_message}"
    )
    try:
        title = await call_llm(prompt, temperature=0.5, use_reasoning=False)
        return title.strip().strip('"').strip("'")
    except Exception as exc:
        logger.error("Failed to generate session title: %s", exc)
        return "New Chat Session"

async def create_session(user_id: str, paper_id: str = None, topic_id: str = None, title: str = None) -> dict:
    """Create a new chat session in Postgres."""
    try:
        supabase = get_supabase()
        db_title = title or "New Discussion"
        
        response = supabase.table("sessions").insert({
            "user_id": user_id,
            "paper_id": paper_id,
            "topic_id": topic_id,
            "title": db_title,
            "turns": []
        }).execute()
        
        if response.data:
            return response.data[0]
    except Exception as exc:
        logger.error("Failed to create session: %s", exc)
    raise RuntimeError("Could not create chat session in database.")

async def get_session(session_id: str, user_id: str) -> dict | None:
    """Load session by ID, validated against user ownership."""
    try:
        supabase = get_supabase()
        response = supabase.table("sessions")\
            .select("*")\
            .eq("id", session_id)\
            .eq("user_id", user_id)\
            .execute()
        if response.data:
            return response.data[0]
    except Exception as exc:
        logger.error("Failed to fetch session %s: %s", session_id, exc)
    return None

async def list_sessions(user_id: str, limit: int = 50) -> list[dict]:
    """Retrieve all sessions for a user, ordered by most recently updated."""
    try:
        supabase = get_supabase()
        response = supabase.table("sessions")\
            .select("id,title,paper_id,topic_id,created_at,updated_at")\
            .eq("user_id", user_id)\
            .order("updated_at", desc=True)\
            .limit(limit)\
            .execute()
        return response.data or []
    except Exception as exc:
        logger.error("Failed to list sessions for user %s: %s", user_id, exc)
        return []

async def append_turn(session_id: str, user_id: str, role: str, content: str) -> list[dict]:
    """Append a new turn to the session history and update title if it was first message."""
    try:
        supabase = get_supabase()
        session = await get_session(session_id, user_id)
        if not session:
            return []

        turns = session.get("turns", [])
        turns.append({"role": role, "content": content})

        update_data = {
            "turns": turns,
            "updated_at": datetime.utcnow().isoformat() + "Z"
        }

        # Auto generate title if it was the first user message
        if role == "user" and len(turns) == 1:
            generated_title = await generate_session_title(content)
            update_data["title"] = generated_title

        supabase.table("sessions")\
            .update(update_data)\
            .eq("id", session_id)\
            .execute()
        return turns
    except Exception as exc:
        logger.error("Failed to append turn to session %s: %s", session_id, exc)
        return []

async def delete_session(session_id: str, user_id: str) -> bool:
    """Delete a session from database."""
    try:
        supabase = get_supabase()
        response = supabase.table("sessions")\
            .delete()\
            .eq("id", session_id)\
            .eq("user_id", user_id)\
            .execute()
        return bool(response.data)
    except Exception as exc:
        logger.error("Failed to delete session %s: %s", session_id, exc)
        return False

"""
app/models/schemas.py

Pydantic models for FastAPI request/response validation.

Keeping API schemas separate from Cognee graph models means the two can
evolve independently — what the frontend sees doesn't have to mirror what
the graph stores internally.
"""

from typing import Literal

from pydantic import BaseModel, Field


# ── Upload / Job status ───────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    """Returned immediately from POST /upload-paper."""
    job_id: str


class JobStatus(BaseModel):
    """Polled via GET /job-status/{job_id}."""
    job_id: str
    status: Literal["processing", "done", "error"]
    # Human-readable current stage — this is what the frontend progress bar reads.
    stage: str
    # Populated once status == "done"
    paper_id: str | None = None
    # Populated when status == "error"
    error: str | None = None


# ── Roadmap / Gap analysis ────────────────────────────────────────────────────

class ConceptSummary(BaseModel):
    """A single concept as returned in the roadmap and knowledge graph."""
    canonical_name: str
    display_name: str
    definition: str = ""
    category: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    priority: str = "critical"
    resource_urls: list[str] = []
    requires: list[str] = []       # list of canonical_names this concept depends on


class RoadmapResponse(BaseModel):
    """Response from GET /roadmap/{paper_id}."""
    roadmap: list[ConceptSummary]  # topologically ordered, lowest-confidence first
    total_concepts: int
    known_count: int               # concepts where confidence >= threshold
    paper_id: str


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str
    paper_id: str


class ConfidenceSignal(BaseModel):
    """Extracted inline from the professor's response, if detected."""
    concept: str
    signal_type: Literal["understood", "confused", "already_knew"]
    detected_from: str = ""   # the learner's quote that triggered the signal


class ChatResponse(BaseModel):
    response: str
    session_id: str
    confidence_signal: ConfidenceSignal | None = None


# ── Concept confidence update ─────────────────────────────────────────────────

class ConceptUpdateRequest(BaseModel):
    concept_name: str
    action: Literal["understood", "confused", "mastered"]


class ConceptUpdateResponse(BaseModel):
    concept_name: str
    canonical_name: str
    new_confidence: float
    action: str


# ── Knowledge graph ───────────────────────────────────────────────────────────

class KnowledgeGraphResponse(BaseModel):
    """A flat map of canonical_name → confidence for the entire user graph."""
    concepts: dict[str, float]
    total: int

# -*- coding: utf-8 -*-
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


class ArxivUploadRequest(BaseModel):
    url: str


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
    citation_index: int | None = None


class RoadmapModule(BaseModel):
    phase: int
    title: str = ""
    concepts: list[ConceptSummary]

class RoadmapResponse(BaseModel):
    """Response from GET /roadmap/{paper_id}."""
    modules: list[RoadmapModule]
    total_concepts: int
    known_count: int               # concepts where confidence >= threshold
    paper_id: str


# ── Sub-Concept Expansion ─────────────────────────────────────────────────────

class SubConceptItem(BaseModel):
    """A single sub-concept or mathematical building block within a concept."""
    name: str
    canonical_name: str
    definition: str
    is_math: bool = False
    formula: str | None = None          # LaTeX or plain-text formula when is_math=True
    wolfram_result: str | None = None   # Wolfram-verified step-by-step when available


class ConceptExpansionRequest(BaseModel):
    """Body for POST /api/v1/concepts/{concept_id}/expand."""
    paper_id: str


class ConceptExpansionResponse(BaseModel):
    """Response from POST /api/v1/concepts/{concept_id}/expand."""
    concept_name: str
    sub_concepts: list[SubConceptItem]
    wolfram_verified: bool = False      # True if at least one formula was Wolfram-verified


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str | None = None
    session_id: str | None = None
    paper_id: str | None = None
    deep_study_mode: bool = False


class ConfidenceSignal(BaseModel):
    """Extracted inline from the professor's response, if detected."""
    concept: str
    signal_type: Literal["understood", "confused", "already_knew"]
    detected_from: str = ""   # the learner's quote that triggered the signal


class ChatResponse(BaseModel):
    response: str
    session_id: str
    confidence_signal: ConfidenceSignal | None = None
    verified_by_wolfram: bool = False   # True when the response included Wolfram math verification


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


# ── Paper Details ─────────────────────────────────────────────────────────────

class PaperResponse(BaseModel):
    id: str
    title: str
    filename: str
    pdf_url: str | None = None


# ── References & Citations ────────────────────────────────────────────────────

class PaperReference(BaseModel):
    """A single reference or inbound citation entry."""
    title: str
    year: int | None = None
    authors: list[str] = []
    semantic_scholar_url: str = ""


class PaperReferencesResponse(BaseModel):
    """Response from GET /api/v1/papers/{paper_id}/references."""
    paper_id: str
    arxiv_id: str | None = None
    references: list[PaperReference]   # papers this paper cites (oldest first)
    citations: list[PaperReference]    # papers citing this one (newest first)


# ── Topic Mode ────────────────────────────────────────────────────────────────

class TopicCreateRequest(BaseModel):
    seed_arxiv_id: str
    size: int = Field(default=10, ge=5, le=30)


# ── Citations Registry ────────────────────────────────────────────────────────

class CitationItem(BaseModel):
    id: int
    citation_index: int
    source_type: str
    title: str
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    is_preprint: bool = False
    influence_score: float = 0.0

class CitationsResponse(BaseModel):
    paper_id: str
    session_id: str | None = None
    citations: list[CitationItem]



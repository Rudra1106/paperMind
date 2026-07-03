"""
app/api/endpoints.py

All FastAPI route handlers.

Six endpoints:
  POST /upload-paper       — async, returns job_id immediately
  GET  /job-status/{id}    — polls upload progress
  GET  /roadmap/{paper_id} — gap analysis + topological roadmap
  POST /chat               — professor agent turn
  POST /concept/update     — manual confidence update
  GET  /knowledge-graph    — full user confidence map

The upload-paper / job-status pair (plan Part 2 Section 8.1) is the key
async pattern: PDF processing takes 15-30 seconds on a cold run. Returning
immediately with a job_id and letting the frontend poll is the correct
pattern — a synchronous 25-second open connection reads as "broken" to a
judge watching in real time.
"""

import asyncio
import hashlib
import logging
import uuid

import cognee
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse

from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ConceptSummary,
    ConceptUpdateRequest,
    ConceptUpdateResponse,
    JobStatus,
    KnowledgeGraphResponse,
    RoadmapResponse,
    UploadResponse,
    ConfidenceSignal,
)
from app.pipelines import concept_pipeline, pdf_pipeline, scholar_pipeline, wiki_pipeline
from app.services import chat as chat_service
from app.services import confidence as confidence_service
from app.services.cognee_write import write_paper_to_cognee
from app.services.roadmap import compute_gap, topological_roadmap
from app.utils.cache_manager import get_paper_result, save_paper_result
from app.utils.canonical import canonical

logger = logging.getLogger(__name__)
router = APIRouter()

# ── In-memory job store ───────────────────────────────────────────────────────
# Fine for a single-user demo. Multi-user would need Redis or a DB.
jobs: dict[str, dict] = {}


# ── Background upload job ─────────────────────────────────────────────────────

async def process_paper_job(job_id: str, pdf_bytes: bytes, filename: str) -> None:
    """
    Full paper processing pipeline, run as a FastAPI background task.

    Stages (visible via /job-status polling):
      checking_cache → extracting_text → extracting_concepts_and_indexing →
      mapping_dependencies → enriching_wikipedia → enriching_scholar →
      writing_to_graph → complete

    Each set_stage() call is what the frontend progress bar reads.
    """
    def set_stage(stage: str) -> None:
        jobs[job_id]["stage"] = stage
        logger.info("[job %s] stage: %s", job_id, stage)

    try:
        # 1. Cache check — skip entire pipeline for re-uploads
        set_stage("checking_cache")
        pdf_hash = hashlib.md5(pdf_bytes).hexdigest()
        cached = get_paper_result(pdf_hash)
        if cached:
            logger.info("[job %s] cache hit for %s", job_id, filename)
            jobs[job_id] = {
                "status": "done",
                "stage": "cache_hit",
                "paper_id": cached["paper_id"],
                "error": None,
            }
            return

        # 2. PDF extraction
        set_stage("extracting_text")
        full_text = pdf_pipeline.extract_full_text(pdf_bytes)
        sections = pdf_pipeline.detect_sections(full_text)
        text_slice = pdf_pipeline.get_extraction_slice(sections)

        paper_id = str(uuid.uuid4())

        # 3. Track A (concept extraction) and Track B (full-text Cognee indexing)
        # run concurrently — they don't depend on each other at all.
        set_stage("extracting_concepts_and_indexing")

        async def _cognee_fulltext_ingest() -> None:
            """Index the full paper text in Cognee for chatbot RAG."""
            try:
                await cognee.remember(full_text, dataset_name=f"paper_{paper_id}_fulltext")
            except Exception as exc:
                # Don't abort the whole pipeline — RAG is a nice-to-have layer
                logger.warning("Full-text Cognee ingestion failed: %s", exc)

        concepts_task = asyncio.create_task(concept_pipeline.extract_concepts(text_slice))
        fulltext_task = asyncio.create_task(_cognee_fulltext_ingest())

        parsed_concepts, _ = await asyncio.gather(concepts_task, fulltext_task)
        concepts = parsed_concepts["concepts"]
        paper_title = parsed_concepts.get("paper_title", filename)

        # 4. Dependency mapping
        set_stage("mapping_dependencies")
        edges = await concept_pipeline.map_dependencies(concepts)

        # 5. Wikipedia enrichment (concurrent across all concepts)
        set_stage("enriching_wikipedia")
        enriched = await wiki_pipeline.enrich_all([c["canonical_name"] for c in concepts])

        # 6. Semantic Scholar enrichment
        set_stage("enriching_scholar")
        await scholar_pipeline.get_paper_references(paper_title)

        # 7. Write typed DataPoints into Cognee graph
        set_stage("writing_to_graph")
        await write_paper_to_cognee(concepts, edges, enriched, paper_id)

        # 8. Cross-paper reinforcement for known concepts
        await confidence_service.mark_concepts_from_paper(concepts)

        # 9. Cache the result — re-uploads skip everything above
        save_paper_result(pdf_hash, {
            "paper_id": paper_id,
            "concepts": concepts,
            "edges": edges,
            "paper_title": paper_title,
        })

        jobs[job_id] = {
            "status": "done",
            "stage": "complete",
            "paper_id": paper_id,
            "error": None,
        }

    except Exception as exc:
        logger.exception("[job %s] failed at stage '%s'", job_id, jobs[job_id].get("stage"))
        jobs[job_id] = {
            "status": "error",
            "stage": jobs[job_id].get("stage", "unknown"),
            "paper_id": None,
            "error": str(exc),
        }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload-paper", response_model=UploadResponse, summary="Upload a research paper PDF")
async def upload_paper(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF file of the research paper"),
) -> UploadResponse:
    """
    Accept a PDF upload and immediately return a job_id.
    The actual processing runs asynchronously in the background.
    Poll /job-status/{job_id} to track progress.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "processing", "stage": "queued", "paper_id": None, "error": None}

    background_tasks.add_task(process_paper_job, job_id, contents, file.filename)
    return UploadResponse(job_id=job_id)


@router.get("/job-status/{job_id}", response_model=JobStatus, summary="Check paper processing status")
async def get_job_status(job_id: str) -> JobStatus:
    """Poll this endpoint after uploading a paper to track processing progress."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return JobStatus(job_id=job_id, **job)


@router.get("/roadmap/{paper_id}", response_model=RoadmapResponse, summary="Get the learning roadmap for a paper")
async def get_roadmap(paper_id: str) -> RoadmapResponse:
    """
    Returns the gap analysis and topologically ordered learning roadmap
    for the authenticated user and the specified paper.
    """
    # Find the cached result for this paper_id
    from app.utils.cache_manager import concepts_cache
    paper_data = None
    for cached in concepts_cache._data.values():
        if isinstance(cached, dict) and cached.get("paper_id") == paper_id:
            paper_data = cached
            break

    if not paper_data:
        raise HTTPException(
            status_code=404,
            detail=f"Paper '{paper_id}' not found. Please upload it first.",
        )

    concepts = paper_data.get("concepts", [])
    edges = paper_data.get("edges", {})

    user_confidence = confidence_service.get_all_confidence_scores()
    gap = compute_gap(concepts, user_confidence)
    ordered_roadmap = topological_roadmap(gap, edges)

    roadmap_items = [
        ConceptSummary(
            canonical_name=c["canonical_name"],
            display_name=c.get("display_name", c["name"]),
            definition=c.get("definition", ""),
            category=c.get("category", "prerequisite"),
            confidence=c.get("confidence", 0.0),
            priority=c.get("priority", "critical"),
            resource_urls=c.get("resource_urls", []),
            requires=edges.get(c["canonical_name"], []),
        )
        for c in ordered_roadmap
    ]

    return RoadmapResponse(
        roadmap=roadmap_items,
        total_concepts=len(concepts),
        known_count=len(concepts) - len(gap),
        paper_id=paper_id,
    )


@router.post("/chat", response_model=ChatResponse, summary="Chat with the professor agent")
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Send a message to the professor agent for a specific paper and session.
    The agent uses the user's knowledge graph to personalize explanations.
    """
    session = chat_service.get_or_create_session(request.session_id, request.paper_id)

    # Load context from Cognee graph
    context = await chat_service.build_professor_context(request.paper_id, request.message)

    # Load user's current knowledge state
    user_confidence = confidence_service.get_all_confidence_scores()

    # Load paper concepts for gap list
    from app.utils.cache_manager import concepts_cache
    paper_data = None
    for cached in concepts_cache._data.values():
        if isinstance(cached, dict) and cached.get("paper_id") == request.paper_id:
            paper_data = cached
            break

    gap_concepts = []
    if paper_data:
        gap_concepts = compute_gap(paper_data.get("concepts", []), user_confidence)

    # Run the professor turn
    result = await chat_service.run_professor_turn(
        session=session,
        message=request.message,
        known_concepts=user_confidence,
        gap_concepts=gap_concepts,
        context=context,
    )

    # Handle confidence signal if detected
    conf_signal = None
    if result.get("confidence_signal"):
        signal = result["confidence_signal"]
        await confidence_service.handle_confidence_signal(signal)
        conf_signal = ConfidenceSignal(**signal) if isinstance(signal, dict) else None

    # Append to session history
    session.turns.append({"role": "user", "content": request.message})
    session.turns.append({"role": "assistant", "content": result["response"]})
    chat_service.persist_session_snapshot(session)

    return ChatResponse(
        response=result["response"],
        session_id=request.session_id,
        confidence_signal=conf_signal,
    )


@router.post("/concept/update", response_model=ConceptUpdateResponse, summary="Manually update concept confidence")
async def update_concept(request: ConceptUpdateRequest) -> ConceptUpdateResponse:
    """
    Explicitly mark a concept as understood, confused, or mastered.
    Useful for the roadmap UI's direct feedback buttons.
    """
    new_confidence = await confidence_service.manual_update(request.concept_name, request.action)
    return ConceptUpdateResponse(
        concept_name=request.concept_name,
        canonical_name=canonical(request.concept_name),
        new_confidence=new_confidence,
        action=request.action,
    )


@router.get("/knowledge-graph", response_model=KnowledgeGraphResponse, summary="Get the user's full knowledge graph")
async def get_knowledge_graph() -> KnowledgeGraphResponse:
    """
    Returns the full confidence map for the current user.
    Used by the frontend to render the knowledge graph visualization.
    """
    scores = confidence_service.get_all_confidence_scores()
    return KnowledgeGraphResponse(concepts=scores, total=len(scores))


@router.get("/health", include_in_schema=False)
async def health_check() -> dict:
    return {"status": "ok"}

"""
app/api/endpoints.py

All FastAPI route handlers.
Upgraded to use Supabase for Auth, Jobs, and Confidence (Phase 2).
Phase 4: added concept expansion, paper references, cache admin endpoints.
"""

import asyncio
import hashlib
import logging
import uuid
from typing import Annotated

import cognee
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Depends
from fastapi.responses import JSONResponse

from app.core.auth import CurrentUser
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ConceptExpansionRequest,
    ConceptExpansionResponse,
    ConceptSummary,
    ConceptUpdateRequest,
    ConceptUpdateResponse,
    JobStatus,
    KnowledgeGraphResponse,
    PaperReference,
    PaperReferencesResponse,
    RoadmapResponse,
    SubConceptItem,
    UploadResponse,
    ConfidenceSignal,
    ArxivUploadRequest,
    TopicCreateRequest,
    PaperResponse,
    CitationsResponse,
    CitationItem,
)
from app.pipelines import concept_pipeline, pdf_pipeline, scholar_pipeline, wiki_pipeline, arxiv_pipeline
from app.services import chat as chat_service
from app.services import confidence as confidence_service
from app.services.cognee_write import write_paper_to_cognee
from app.services.roadmap import compute_gap
from app.services import job_store, paper_store
from app.utils.canonical import canonical

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Background upload job ─────────────────────────────────────────────────────

async def process_paper_job(user_id: str, job_id: str, pdf_bytes: bytes, filename: str) -> None:
    """
    DAG-based step-resumable processing pipeline run as a background task.
    Observes and caches each step in Postgres.
    """
    from app.services.pipeline_registry import get_or_run_step
    from app.agents import ingestion_agent, extraction_agent, enrichment_agent, verification_agent, dependency_agent

    async def set_stage(stage: str) -> None:
        await job_store.set_stage(job_id, stage)

    try:
        await set_stage("checking_cache")
        pdf_hash = hashlib.md5(pdf_bytes).hexdigest()
        
        # 1. Cache check (Fast DB check, no need for step tracking)
        cached_paper = await paper_store.get_paper_by_hash(pdf_hash)
        if cached_paper:
            logger.info("[job %s] cache hit for %s", job_id, filename)
            await job_store.complete_job(job_id, cached_paper["id"])
            return

        # Generate stable paper ID based on PDF hash to make steps resumable across retries
        paper_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, pdf_hash))

        # Note: We preserve pipeline_steps so if a job fails (e.g. server restart or timeout),
        # the user can re-upload the same PDF and instantly skip the completed steps.

        # Step 1: Ingestion (Deterministic parser + math formula extraction)
        await set_stage("ingesting_pdf")
        raw = await get_or_run_step(
            paper_id, "ingest",
            ingestion_agent.run, pdf_bytes, filename
        )

        # Step 2: Storage Upload (Save raw PDF to Supabase Storage)
        await set_stage("uploading_to_storage")
        storage_path = await get_or_run_step(
            paper_id, "upload_storage",
            paper_store.upload_pdf_to_storage, user_id, pdf_bytes, pdf_hash
        )

        # Step 3: Concept Extraction (LLM call with evidence grounding)
        await set_stage("extracting_concepts")
        extracted = await get_or_run_step(
            paper_id, "extract_concepts",
            extraction_agent.run, raw["text_slice"], raw["full_text"]
        )
        concepts = extracted["concepts"]
        paper_title = extracted.get("paper_title", raw["title"])

        # Step 4: Enrichment (Tool routing + Wiki/Scholar/Wolfram concurrent lookup)
        await set_stage("enriching_concepts")
        enrichment_result = await get_or_run_step(
            paper_id, "enrich_concepts",
            enrichment_agent.run, concepts, raw["equations"], paper_title, paper_id
        )
        enriched_data = enrichment_result.get("concepts", {})

        # Merge enrichment definitions and citations into the concept objects
        for c in concepts:
            canon = canonical(c["name"])
            if canon in enriched_data:
                c["definition"] = enriched_data[canon].get("definition")
                c["resource_urls"] = enriched_data[canon].get("resource_urls", [])
                c["citation_index"] = enriched_data[canon].get("citation_index")

        # Step 5: Verification (Evidence verification + semantic contradiction check)
        await set_stage("verifying_concepts")
        verification_result = await get_or_run_step(
            paper_id, "verify_concepts",
            verification_agent.run, concepts, raw["full_text"]
        )
        verified_concepts = verification_result.get("concepts", concepts)

        # Step 6: Dependency Mapping (Calculates topology, consumes citation prior)
        await set_stage("mapping_dependencies")
        deps_result = await get_or_run_step(
            paper_id, "map_dependencies",
            dependency_agent.run, verified_concepts, raw["arxiv_id"]
        )
        edges = deps_result.get("edges", {})

        # Step 7: Write to Graph (Cognee remember + Postgres Save)
        await set_stage("writing_to_graph")
        
        async def _write_graph():
            # Ingest chunked text into Cognee for semantic chat searches
            try:
                import textwrap
                # Split the raw text into manageable chunks of ~1000 chars
                chunks = textwrap.wrap(raw["full_text"], width=1000, break_long_words=False, replace_whitespace=False)
                if chunks:
                    from cognee.modules.users.models import User
                    import uuid
                    cognee_user = User(id=uuid.UUID(user["id"])) if user["id"] and user["id"] != "default" else None
                    await cognee.remember(chunks, dataset_name=f"paper_{paper_id}_fulltext", user=cognee_user)
            except Exception as exc:
                logger.warning("Full-text Cognee ingestion failed: %s", exc)

            # Write concepts and requires edges into Cognee
            await write_paper_to_cognee(verified_concepts, edges, {}, paper_id, user["id"])

            # Apply cross-paper reinforcement logic
            await confidence_service.mark_concepts_from_paper(user_id, verified_concepts)

            # Save the final structured paper record
            await paper_store.save_paper(
                paper_id=paper_id,
                pdf_hash=pdf_hash,
                title=paper_title,
                filename=filename,
                concepts=verified_concepts,
                edges=edges,
                storage_path=storage_path,
                arxiv_id=raw.get("arxiv_id"),
            )
            return {"paper_id": paper_id}

        await get_or_run_step(paper_id, "write_graph", _write_graph)

        # Complete job
        await job_store.complete_job(job_id, paper_id)

    except Exception as exc:
        logger.exception("[job %s] failed", job_id)
        await job_store.fail_job(job_id, "failed", str(exc))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload-paper", response_model=UploadResponse)
async def upload_paper(
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> UploadResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    job_id = str(uuid.uuid4())
    pdf_hash = hashlib.md5(contents).hexdigest()
    
    import os
    if os.getenv("DEMO_MODE") == "true":
        import json
        fixture_path = os.path.join(os.path.dirname(__file__), "../../../fixtures/attention_demo.json")
        if os.path.exists(fixture_path):
            try:
                with open(fixture_path, "r") as f:
                    demo_data = json.load(f)
                demo_paper = demo_data["paper"]
                demo_hash = demo_paper["pdf_hash"]
                await job_store.create_job(job_id, user["id"], demo_hash)
                
                # Ensure the paper is saved in the DB from the fixture if it's somehow missing
                existing = await paper_store.get_paper_by_hash(demo_hash)
                if not existing:
                    await paper_store.save_paper(
                        demo_paper["id"],
                        demo_paper["pdf_hash"],
                        demo_paper["title"],
                        demo_paper["filename"],
                        demo_paper["concepts"],
                        demo_paper["edges"],
                        demo_paper["storage_path"],
                        demo_paper.get("arxiv_id")
                    )
                
                await job_store.complete_job(job_id, demo_paper["id"])
                return UploadResponse(job_id=job_id)
            except Exception as e:
                logger.error(f"Failed to load demo fixture: {e}")

    await job_store.create_job(job_id, user["id"], pdf_hash)
    background_tasks.add_task(process_paper_job, user["id"], job_id, contents, file.filename)
    
    return UploadResponse(job_id=job_id)



@router.post("/upload-arxiv", response_model=UploadResponse)
async def upload_arxiv(
    request: ArxivUploadRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
) -> UploadResponse:
    try:
        contents, filename = await arxiv_pipeline.fetch_arxiv_pdf(request.url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
        
    job_id = str(uuid.uuid4())
    pdf_hash = hashlib.md5(contents).hexdigest()
    
    await job_store.create_job(job_id, user["id"], pdf_hash)
    background_tasks.add_task(process_paper_job, user["id"], job_id, contents, filename)
    
    return UploadResponse(job_id=job_id)


@router.get("/job-status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str) -> JobStatus:
    job = await job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        stage=job["stage"],
        paper_id=job.get("paper_id"),
        error=job.get("error")
    )


import time
_roadmap_cache = {}

def _invalidate_roadmap_cache(user_id: str):
    keys_to_delete = [k for k in _roadmap_cache.keys() if k[0] == user_id]
    for k in keys_to_delete:
        del _roadmap_cache[k]
from app.models.schemas import ConceptSummary, RoadmapResponse, RoadmapModule
from app.services.roadmap import compute_gap, phased_topological_roadmap, generate_roadmap_titles_async
import asyncio

@router.get("/roadmap/{paper_id}", response_model=RoadmapResponse)
async def get_roadmap(paper_id: str, user: CurrentUser) -> RoadmapResponse:
    cache_key = (user["id"], paper_id)
    now = time.time()
    
    if cache_key in _roadmap_cache:
        _, cached_response = _roadmap_cache[cache_key]
        return cached_response
    paper_data = await paper_store.get_paper_by_id(paper_id)
    if not paper_data:
        raise HTTPException(status_code=404, detail="Paper not found.")

    concepts = paper_data.get("concepts", [])
    edges = paper_data.get("edges", {})

    user_confidence = await confidence_service.get_all_confidence_scores(user["id"])
    # The roadmap is from scratch, so we want all concepts. compute_gap with high threshold includes all.
    # Actually, we'll just ignore confidence for the structure but keep it for UI display.
    gap = compute_gap(concepts, user_confidence, threshold=2.0) # threshold 2.0 ensures all concepts are gaps
    
    phased_modules = phased_topological_roadmap(gap, edges)

    roadmap_modules = []
    for m in phased_modules:
        concept_summaries = [
            ConceptSummary(
                canonical_name=c["canonical_name"],
                display_name=c.get("display_name") or c["name"],
                definition=c.get("definition") or "",
                category=c.get("category") or "prerequisite",
                confidence=c.get("confidence") or 0.0,
                priority=c.get("priority") or "critical",
                resource_urls=c.get("resource_urls") or [],
                requires=edges.get(c["canonical_name"]) or [],
                citation_index=c.get("citation_index"),
            )
            for c in m["concepts"]
        ]
        roadmap_modules.append(
            RoadmapModule(
                phase=m["phase"],
                title=m["title"],
                concepts=concept_summaries
            )
        )

    # Recompute known_count for actual gap threshold (0.6) just for stats
    actual_gap = compute_gap(concepts, user_confidence, threshold=0.6)

    response = RoadmapResponse(
        modules=roadmap_modules,
        total_concepts=len(concepts),
        known_count=len(concepts) - len(actual_gap),
        paper_id=paper_id,
    )
    _roadmap_cache[cache_key] = (now, response)

    # Fire background task to generate rich titles
    paper_title = paper_data.get("metadata", {}).get("title", "Paper")
    asyncio.create_task(
        generate_roadmap_titles_async(phased_modules, _roadmap_cache, cache_key, paper_title)
    )

    return response


@router.get("/papers/{paper_id}", response_model=PaperResponse)
async def get_paper(paper_id: str, user: CurrentUser) -> PaperResponse:
    paper_data = await paper_store.get_paper_by_id(paper_id)
    if not paper_data:
        raise HTTPException(status_code=404, detail="Paper not found.")

    pdf_url = await paper_store.get_paper_pdf_url(paper_id)
    return PaperResponse(
        id=paper_data["id"],
        title=paper_data["title"],
        filename=paper_data["filename"],
        pdf_url=pdf_url
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: CurrentUser) -> ChatResponse:
    from app.services import session_store
    from app.agents import professor_agent
    
    # 1. Fetch or create session in Postgres
    session_id = request.session_id
    if session_id == "new" or not session_id:
        db_sess = await session_store.create_session(user["id"], paper_id=request.paper_id)
        session_id = str(db_sess["id"])
    else:
        db_sess = await session_store.get_session(session_id, user["id"])
        if not db_sess:
            db_sess = await session_store.create_session(user["id"], paper_id=request.paper_id)
            session_id = str(db_sess["id"])

    # 2. Get user confidence scores and compute gaps
    user_confidence = await confidence_service.get_all_confidence_scores(user["id"])
    known_names = [k for k, v in user_confidence.items() if v >= 0.6]
    
    paper_data = await paper_store.get_paper_by_id(request.paper_id)
    gap_concepts = []
    if paper_data:
        gap_concepts = compute_gap(paper_data.get("concepts", []), user_confidence)
    gap_names = [c["canonical_name"] for c in gap_concepts]

    # 3. Retrieve paper graph context from Cognee
    context = await chat_service.build_professor_context(request.paper_id, request.message, user["id"])
    prereqs = context.get("prereq_edges", [])
    explanation = context.get("graph_explanation", "")
    chunks = context.get("similar_chunks", [])
    
    paper_context = (
        f"Relevant concept dependencies:\n{prereqs}\n\n"
        f"Concept relationships explanation:\n{explanation}\n\n"
        f"Semantic paper excerpts:\n" + "\n".join(chunks)
    )

    # 4. Run professor agent turn
    result = await professor_agent.run_professor_turn(
        message=request.message,
        turns=db_sess.get("turns", []),
        known_concepts=known_names,
        gap_concepts=gap_names,
        paper_context=paper_context,
        paper_id=request.paper_id,
        session_id=session_id,
        deep_study_mode=request.deep_study_mode,
    )

    # 5. Save turns to DB
    await session_store.append_turn(session_id, user["id"], "user", request.message)
    await session_store.append_turn(session_id, user["id"], "assistant", result["response"])

    # 6. Apply confidence update signal if detected
    conf_signal = None
    if result.get("confidence_signal"):
        signal = result["confidence_signal"]
        await confidence_service.handle_confidence_signal(user["id"], signal)
        _invalidate_roadmap_cache(user["id"])
        conf_signal = ConfidenceSignal(**signal) if isinstance(signal, dict) else None

    return ChatResponse(
        response=result["response"],
        session_id=session_id,
        confidence_signal=conf_signal,
        verified_by_wolfram=result.get("verified_by_wolfram", False),
    )

@router.post("/concept/update", response_model=ConceptUpdateResponse)
async def update_concept(request: ConceptUpdateRequest, user: CurrentUser) -> ConceptUpdateResponse:
    new_confidence = await confidence_service.manual_update(user["id"], request.concept_name, request.action)
    _invalidate_roadmap_cache(user["id"])
    return ConceptUpdateResponse(
        concept_name=request.concept_name,
        canonical_name=canonical(request.concept_name),
        new_confidence=new_confidence,
        action=request.action,
    )
@router.get("/sessions")
async def list_user_sessions(user: CurrentUser) -> list[dict]:
    from app.services import session_store
    return await session_store.list_sessions(user["id"])

@router.get("/sessions/{session_id}")
async def get_user_session(session_id: str, user: CurrentUser) -> dict:
    from app.services import session_store
    session = await session_store.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session

@router.delete("/sessions/{session_id}")
async def delete_user_session(session_id: str, user: CurrentUser) -> dict:
    from app.services import session_store
    success = await session_store.delete_session(session_id, user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="Session not found or delete failed.")
    return {"status": "deleted"}



@router.get("/knowledge-graph", response_model=KnowledgeGraphResponse)
async def get_knowledge_graph(user: CurrentUser) -> KnowledgeGraphResponse:
    scores = await confidence_service.get_all_confidence_scores(user["id"])
    return KnowledgeGraphResponse(concepts=scores, total=len(scores))


# ── Topic Mode Endpoints ──────────────────────────────────────────────────────

@router.post("/topics")
async def create_topic(request: TopicCreateRequest, user: CurrentUser) -> dict:
    from app.services import topic_service
    try:
        topic_id = await topic_service.create_topic_from_arxiv(
            user_id=user["id"],
            seed_arxiv_id=request.seed_arxiv_id,
            max_papers=request.size
        )
        return {"topic_id": topic_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/topics/{topic_id}")
async def get_topic_reading_order(topic_id: str, user: CurrentUser) -> list[dict]:
    from app.services import topic_service
    return await topic_service.compute_reading_order(topic_id, user["id"])

@router.get("/topics/{topic_id}/paper/{paper_id}/overlap")
async def get_topic_paper_overlap(topic_id: str, paper_id: str, user: CurrentUser) -> dict:
    from app.services import topic_service
    return await topic_service.compute_paper_overlap(user["id"], paper_id)

@router.get("/topics/{topic_id}/paper/{paper_id}/timeline")
async def get_topic_paper_timeline(topic_id: str, paper_id: str, user: CurrentUser) -> dict:
    from app.services import topic_service
    return await topic_service.classify_inherited_vs_novel(paper_id, topic_id)


# ── Concept expansion endpoint ────────────────────────────────────────────────

@router.post("/concepts/{concept_id}/expand", response_model=ConceptExpansionResponse)
async def expand_concept(
    concept_id: str,
    request: ConceptExpansionRequest,
    user: CurrentUser,
) -> ConceptExpansionResponse:
    """
    Expand a concept into its 3-5 foundational sub-concepts / math building blocks.
    Results are cached per (concept, paper) pair — repeat calls are instant.
    """
    from app.agents import expansion_agent
    from app.services import chat as chat_service

    # Fetch paper context chunks to ground the expansion
    context = await chat_service.build_professor_context(request.paper_id, concept_id, user["id"])
    chunks = context.get("similar_chunks", [])
    chunk_context = "\n".join([c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in chunks])

    # concept_id here is the canonical name
    concept_display = concept_id.replace("_", " ")

    result = await expansion_agent.run(
        concept_name=concept_display,
        chunk_context=chunk_context,
        paper_id=request.paper_id,
    )

    sub_concept_items = [
        SubConceptItem(
            name=sc["name"],
            canonical_name=sc.get("canonical_name", canonical(sc["name"])),
            definition=sc.get("definition", ""),
            is_math=sc.get("is_math", False),
            formula=sc.get("formula"),
            wolfram_result=sc.get("wolfram_result"),
        )
        for sc in result.get("sub_concepts", [])
    ]

    return ConceptExpansionResponse(
        concept_name=concept_display,
        sub_concepts=sub_concept_items,
        wolfram_verified=result.get("wolfram_verified", False),
    )


# ── Paper references endpoint ─────────────────────────────────────────────────

@router.get("/papers/{paper_id}/references", response_model=PaperReferencesResponse)
async def get_paper_references(
    paper_id: str,
    user: CurrentUser,
) -> PaperReferencesResponse:
    """
    Fetch the reference list and inbound citations for a paper via Semantic Scholar.
    Requires the paper to have an arXiv ID stored in its metadata.
    """
    from app.clients import semantic_scholar_client

    paper_data = await paper_store.get_paper_by_id(paper_id)
    if not paper_data:
        raise HTTPException(status_code=404, detail="Paper not found.")

    # arXiv ID may be stored in the paper's edges or concepts metadata
    arxiv_id = paper_data.get("arxiv_id") or paper_data.get("metadata", {}).get("arxiv_id")
    if not arxiv_id:
        raise HTTPException(
            status_code=422,
            detail="This paper does not have an arXiv ID — references cannot be fetched.",
        )

    refs_data = await semantic_scholar_client.fetch_paper_references(arxiv_id)

    return PaperReferencesResponse(
        paper_id=paper_id,
        arxiv_id=arxiv_id,
        references=[
            PaperReference(
                title=r["title"],
                year=r.get("year"),
                authors=r.get("authors", []),
                semantic_scholar_url=r.get("semantic_scholar_url", ""),
            )
            for r in refs_data.get("references", [])
        ],
        citations=[
            PaperReference(
                title=c["title"],
                year=c.get("year"),
                authors=c.get("authors", []),
                semantic_scholar_url=c.get("semantic_scholar_url", ""),
            )
            for c in refs_data.get("citations", [])
        ],
    )
  

# ── Citations Registry Endpoint ───────────────────────────────────────────────

@router.get("/papers/{paper_id}/citations", response_model=CitationsResponse)
async def get_citations_endpoint(
    paper_id: str,
    user: CurrentUser,
    session_id: str | None = None,
) -> CitationsResponse:
    """
    Retrieve all registered citations for a paper, combined with any session-specific citations.
    """
    from app.services import citation_registry
    
    citations = await citation_registry.get_citations(paper_id, session_id)
    return CitationsResponse(
        paper_id=paper_id,
        session_id=session_id,
        citations=citations,
    )


# ── Admin: cache invalidation ─────────────────────────────────────────────────

@router.post("/admin/cache/invalidate", include_in_schema=False)
async def invalidate_cache(
    concept: str,
    user: CurrentUser,
) -> dict:
    """
    Spot-invalidate cached external API entries for a specific concept name.
    Useful for flushing stale Wikipedia/Scholar/Wolfram results without
    a full cache version bump or redeploy.

    Example: POST /api/v1/admin/cache/invalidate?concept=transformer
    """
    from app.services.external_cache import invalidate_concept_cache
    deleted = await invalidate_concept_cache(concept)
    return {"concept": concept, "entries_deleted": deleted}


@router.get("/health", include_in_schema=False)
async def health_check() -> dict:
    return {"status": "ok"}

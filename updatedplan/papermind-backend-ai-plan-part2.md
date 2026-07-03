# PaperMind — Backend & AI Implementation Plan
### Part 2: Confidence engine internals, FastAPI async job pattern, caching implementation, day-by-day build checklist

Continues directly from Part 1 (Cognee data layer, OpenRouter/LLM pipeline, gap analysis, professor agent). Read that first if you haven't.

---

## 7 (cont'd). Confidence Scoring Engine — the race condition and how to close it

### 7.5 Why this is a real risk, not a theoretical one

Your confidence update flow is `forget()` old fact → `remember()` new fact. Between those two calls, the graph briefly has *no* entry for that concept. If two updates for the same concept fire close together — realistic in a demo where a judge might type "I understood attention" right as your `improve()` end-of-session consolidation is also recalculating that same concept — you can get a lost update: whichever `remember()` lands last wins, and the other update silently vanishes. In a hackathon demo, "the score didn't go up when I said I understood it" is a visible, embarrassing failure in front of judges.

The fix doesn't need anything heavyweight. A single in-process `asyncio.Lock` per concept, held for the full forget-then-remember cycle, is enough for a single-user, single-process demo:

```python
# knowledge/confidence.py
import asyncio
from collections import defaultdict

_concept_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

async def update_confidence(concept_name: str, delta: float | None = None,
                              set_value: float | None = None, source: str = "chat") -> float:
    canonical_name = canonical(concept_name)
    async with _concept_locks[canonical_name]:
        current = await get_current_confidence(canonical_name)  # reads user_knowledge
        new_value = set_value if set_value is not None else \
            max(0.0, min(1.0, current + delta))

        await cognee.forget(canonical_name, dataset="user_knowledge")
        await cognee.remember(
            format_user_knowledge_ingestion(canonical_name, new_value, source),
            dataset="user_knowledge",
        )
        return new_value
```

The lock is keyed per-concept, not global — updates to *different* concepts still run concurrently, which matters if `improve()` is consolidating a whole session's worth of concepts at once. Only same-concept writes serialize. This is the entire fix; don't build anything more elaborate than this for a single-process hackathon demo. If you were shipping this as a real multi-user product you'd need a distributed lock (Redis) or move to an actual database transaction — flag that as a known limitation in your README rather than building it, since it's not what's being judged.

### 7.6 The four triggers, wired to this function

```python
# Explicit feedback (Prompt 5 classification result from Section 7.4)
async def handle_confidence_signal(signal: dict):
    mapping = {"understood": (+0.3, None), "confused": (-0.1, None), "already_knew": (None, 0.9)}
    delta, set_value = mapping[signal["signal_type"]]
    await update_confidence(signal["concept"], delta=delta, set_value=set_value, source="chat")

# Chat engagement (follow-up question detected)
async def handle_followup_engagement(concept_name: str):
    await update_confidence(concept_name, delta=+0.1, source="chat")

# Cross-paper reinforcement — checked at concept-extraction time for a NEW paper
async def handle_cross_paper_reinforcement(concept_name: str, is_repeat: bool):
    if is_repeat:
        await update_confidence(concept_name, delta=+0.15, source="paper")

# improve() consolidation — batch, at end of session
async def consolidate_session(session: ChatSession):
    await cognee.improve(dataset="user_knowledge")  # bridges session cache -> permanent graph
    for concept_name in session.concepts_discussed:
        await update_confidence(concept_name, delta=0.0, source="improve_consolidation")
        # delta=0.0 here is intentional: this just refreshes last_updated/source
        # metadata for concepts touched this session without double-counting the
        # deltas already applied by the three triggers above during the session
```

That last comment matters: don't let `improve()` consolidation *also* apply a confidence bump on top of what the per-turn triggers already applied, or you'll double-count and confidence scores will climb faster than the interaction actually justifies. `improve()`'s job here is graph housekeeping (bridging ephemeral session memory into the permanent store) and metadata refresh, not a second scoring pass.

---

## 8. FastAPI Backend — the async job-status pattern

### 8.1 Why polling, not a blocking request

`POST /upload-paper` triggers pdfplumber extraction → LLM concept extraction → LLM dependency mapping → concurrent Wikipedia enrichment → Semantic Scholar → Cognee writes. Even with caching and concurrency, a cold upload is realistically 15-30 seconds. A blocking HTTP request that long is bad practice generally, and specifically dangerous in a live demo — any network hiccup during a 20-second open connection reads as "the app is broken" to a judge watching over your shoulder. Return immediately with a job ID, let the frontend poll.

```python
# main.py
from fastapi import FastAPI, UploadFile, BackgroundTasks
from pydantic import BaseModel
import uuid

app = FastAPI()
jobs: dict[str, dict] = {}   # in-memory job store, fine for single-user demo

class JobStatus(BaseModel):
    job_id: str
    status: str          # "processing" | "done" | "error"
    stage: str            # human-readable current stage, for UI progress text
    paper_id: str | None = None
    error: str | None = None

@app.post("/upload-paper")
async def upload_paper(file: UploadFile, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    contents = await file.read()
    jobs[job_id] = {"status": "processing", "stage": "queued", "paper_id": None, "error": None}
    background_tasks.add_task(process_paper_job, job_id, contents, file.filename)
    return {"job_id": job_id}

@app.get("/job-status/{job_id}", response_model=JobStatus)
async def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JobStatus(job_id=job_id, status="error", stage="not_found", error="Unknown job")
    return JobStatus(job_id=job_id, **job)
```

Note this adds a sixth endpoint (`/job-status/{job_id}`) beyond your original five — that's a justified addition, not scope creep: without it, `/upload-paper` cannot honestly return quickly, and a synchronous version of that endpoint is a worse design for a live demo. If a judge asks why there are six endpoints instead of five, this is a one-sentence, confident answer.

### 8.2 The background job function — staged, with visible progress

```python
async def process_paper_job(job_id: str, pdf_bytes: bytes, filename: str):
    def set_stage(stage: str):
        jobs[job_id]["stage"] = stage

    try:
        set_stage("checking_cache")
        pdf_hash = hashlib.md5(pdf_bytes).hexdigest()
        cached = cache_manager.get_paper_result(pdf_hash)
        if cached:
            jobs[job_id] = {"status": "done", "stage": "cache_hit", "paper_id": cached["paper_id"], "error": None}
            return

        set_stage("extracting_text")
        sections = pdf_pipeline.extract_and_detect_sections(pdf_bytes)

        set_stage("extracting_concepts")
        concepts = await concept_pipeline.extract_concepts(sections)

        set_stage("mapping_dependencies")
        edges = await concept_pipeline.map_dependencies(concepts)
        edges = validate_and_break_cycles(edges)   # Section 4.4's cycle guard

        set_stage("enriching_wikipedia")
        enriched = await wiki_pipeline.enrich_all([c["name"] for c in concepts])

        set_stage("enriching_scholar")
        scholar_refs = await scholar_pipeline.get_paper_references(sections.get("preamble", ""))

        set_stage("writing_to_graph")
        paper_id = await write_paper_to_cognee(concepts, edges, enriched, scholar_refs, filename)

        cache_manager.save_paper_result(pdf_hash, {"paper_id": paper_id})
        jobs[job_id] = {"status": "done", "stage": "complete", "paper_id": paper_id, "error": None}

    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": jobs[job_id]["stage"], "paper_id": None, "error": str(e)}
```

The `set_stage()` calls aren't just for logging — they're what your Streamlit progress bar reads via polling `/job-status/{job_id}`, which is exactly the "Progress bar: extracting → concepts → dependencies → gap analysis" beat in your own demo script. Building the staged job this way means that UI element is free once the frontend polls this endpoint; you don't need separate instrumentation for it.

Wrap the whole function body in try/except and always end in a defined `jobs[job_id]` state — an unhandled exception that leaves a job permanently stuck at `"processing"` is worse for a live demo than a clean error message, because a stuck spinner gives you nothing to say to a judge while a clear error at least lets you explain and retry.

### 8.3 The remaining endpoints, briefly

The other four endpoints from your original plan don't need the same depth — they're simpler synchronous reads/writes once the graph is populated:

```python
@app.get("/roadmap/{paper_id}")
async def get_roadmap(paper_id: str):
    paper_concepts = await load_paper_concepts(paper_id)
    user_knowledge = await load_user_knowledge_map()
    gap = compute_gap(paper_concepts, user_knowledge)
    edges = await load_dependency_edges(paper_id)
    return {"roadmap": topological_roadmap(gap, edges), "total_concepts": len(paper_concepts), "known_count": len(paper_concepts) - len(gap)}

@app.post("/chat")
async def chat(paper_id: str, message: str, session_id: str):
    session = get_or_create_session(session_id, paper_id)
    context = await build_professor_context(paper_id, message, user_id="default")
    result = await run_professor_turn(session, message, context)   # returns {"response", "confidence_signal"}
    if result["confidence_signal"]:
        await handle_confidence_signal(result["confidence_signal"])
    session.turns.append({"role": "user", "content": message})
    session.turns.append({"role": "assistant", "content": result["response"]})
    persist_session_snapshot(session)   # the crash-safety write from Section 7.1
    return {"response": result["response"]}

@app.post("/concept/update")
async def concept_update(concept_name: str, action: str):
    mapping = {"understood": (+0.3, None), "confused": (-0.1, None), "mastered": (None, 1.0)}
    delta, set_value = mapping[action]
    new_confidence = await update_confidence(concept_name, delta=delta, set_value=set_value, source="manual")
    return {"concept": concept_name, "new_confidence": new_confidence}

@app.get("/knowledge-graph")
async def knowledge_graph():
    return await load_user_knowledge_map()   # {concept_name: confidence, ...}
```

---

## 9. Caching Layer — full implementation

Two caches, both trivial JSON files, both essential to not burning your 200/day OpenRouter budget on repeat testing:

```python
# cache/cache_manager.py
import json, os
from pathlib import Path

CACHE_DIR = Path(".papermind_cache")
CACHE_DIR.mkdir(exist_ok=True)

class JSONCache:
    def __init__(self, filename: str):
        self.path = CACHE_DIR / filename
        self._data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value):
        self._data[key] = value
        self.path.write_text(json.dumps(self._data, indent=2))

concepts_cache = JSONCache("concepts_cache.json")   # keyed by MD5(pdf bytes)
wiki_cache = JSONCache("wiki_cache.json")            # keyed by canonical concept name

def get_paper_result(pdf_hash: str):
    return concepts_cache.get(pdf_hash)

def save_paper_result(pdf_hash: str, result: dict):
    concepts_cache.set(pdf_hash, result)
```

Wrap every Wikipedia fetch with a cache check first — this matters more than it sounds like, because the same foundational concepts ("gradient descent," "attention," "convolution") will recur across nearly every paper a CS/AI-focused demo touches, so the cache hit rate on Wikipedia lookups climbs fast after the first couple of papers:

```python
async def fetch_wikipedia(concept_name: str) -> dict:
    key = canonical(concept_name)
    cached = wiki_cache.get(key)
    if cached:
        return cached
    result = await _fetch_wikipedia_live(concept_name)
    wiki_cache.set(key, result)
    return result
```

One caution: `JSONCache` here rewrites the entire file on every `set()` call, which is fine for a hackathon's data volumes (dozens to low hundreds of entries) but would not scale past that. Don't over-engineer this — a real database here is wasted effort for a 7-day build; note it as a known simplification in your README if a judge asks about scale.

---

## 10. Day-by-Day Checklist, Reconciled Against Today

Today is **July 3**, which your original schedule marks as **Day 5: improve() + forget() feedback loop**. Two honest possibilities, and the right move depends on which is true for you:

**If your Days 1-4 work already exists and roughly matches this deeper plan** — good, today's actual task is Section 7 above (confidence engine + the locking pattern) plus wiring `improve()`/`forget()` into the chat and manual-update endpoints. That's a focused, achievable single day. Tomorrow (Day 6, per your schedule) becomes Streamlit frontend + demo pre-seeding, and Day 7 is polish/README/video — unchanged from your original table.

**If Days 1-4 are thinner than this plan** (e.g., you have PDF ingestion and basic extraction working, but not the fallback model chain, JSON repair, cycle detection, or the async job pattern) — don't try to retrofit all of Part 1 and Part 2 today. Prioritize in this order, because each item is a demo-day failure point in rough order of likelihood and visibility:

1. JSON repair layer (Section 3.2) — silent extraction failures are the most common free-model failure mode and the easiest to fix
2. Cycle detection guard (Section 4.4) — a crash during the roadmap step is the most visible possible failure in front of judges
3. Async job pattern (Section 8.1-8.2) — a hanging upload request reads as "broken" faster than almost anything else
4. Confidence locking (Section 7.5) — lower visible risk than the above three, but worth 20 minutes since it's cheap
5. Model fallback chain (Section 3.1) — nice resilience, lowest priority if time is short since it's a rate-limit mitigation, not a correctness fix

Everything from Part 1 (concept extraction, dependency mapping, gap analysis, professor agent) is assumed built by now per your own schedule; Part 2's additions are hardening, not new features, so they can be layered onto working Day 1-4 code without a rewrite.

### Remaining schedule, restated with the additions folded in

| Day | Date | Core deliverable (yours) | Hardening to fold in (this plan) |
|---|---|---|---|
| 5 | Jul 3 (today) | improve()/forget() feedback loop | confidence locking, JSON repair, cycle guard if not already done |
| 6 | Jul 4 | Streamlit frontend + demo pre-seeding | async job-status polling wired into the progress bar UI |
| 7 | Jul 5 | Polish, README, demo video, submission | note the 6th endpoint and Cognee Cloud-vs-local decision explicitly in the README |

### One demo-day rehearsal note

Before recording the demo video, run the full flow (upload → roadmap → chat → "I understood X" → gap count drop → second paper upload → smaller gap count) **twice in a row on the same machine**, back to back, without restarting the server. This is the single best test for exactly the race-condition and stale-job-state bugs this plan is designed to prevent — if the second run behaves identically to the first, you're demo-safe.

---

That's the full backend + AI plan. If you want, I can next go through the Wikipedia/Semantic Scholar pipeline code in the same level of detail, or the Streamlit frontend structure — but per your framing, backend and AI models were the priority, and that's now covered end to end.

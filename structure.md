# PaperMind Backend Codebase Structure

This document outlines the file and folder layout of the PaperMind backend service, detailing the purpose of each component and providing illustrative code snippets to clarify the architecture.

---

## Directory Overview

```text
backend/
├── app/
│   ├── agents/          # LLM-based agents (Ingestion, Extraction, Enrichment, etc.)
│   ├── api/             # FastAPI routers and route handlers
│   ├── clients/         # External API client integrations (Wikipedia, Scholar, Wolfram)
│   ├── core/            # Configuration, authentication, and database initializations
│   ├── models/          # Pydantic validation schemas
│   ├── pipelines/       # Task execution logic (arXiv downloading, PDF handling)
│   ├── prompts/         # Base prompt templates for agents (if separate)
│   ├── services/        # Database storage wrappers and helper functions
│   └── utils/           # Helper scripts (string sanitizers, local caching)
├── main.py              # Application entrypoint
└── requirements.txt     # Python dependencies list
```

---

## Component Details & Code Samples

### 1. Application Entrypoint (`app/main.py`)
Sets up the FastAPI application, mounts CORS middlewares, registers route handlers, and initializes connections to Cognee on startup.

**Code Pattern:**
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import router as api_router
from app.core.cognee_setup import init_cognee

app = FastAPI(title="PaperMind API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

@app.on_event("startup")
async def startup_event():
    print("PaperMind backend starting up...")
    await init_cognee()
```

---

### 2. API Route Handlers (`app/api/endpoints.py`)
Handles all incoming HTTP requests (CORS, Auth, schema validation) and delegates tasks to background workers. It defines endpoints for uploads, jobs, roadmaps, chats, and topics.

**Code Pattern:**
```python
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
```

---

### 3. Agent Layer (`app/agents/`)
Specialized agent scripts executing individual cognitive stages of the ingestion pipeline.

* **`ingestion_agent.py`**: Extracts text and parses equations from PDF bytes.
* **`extraction_agent.py`**: Identifies key concepts within the document.
* **`enrichment_agent.py`**: Dispatches queries to Wikipedia/Scholar/Wolfram to gather references.
* **`verification_agent.py`**: Checks that the generated definitions map cleanly back to the text to prevent hallucinations.
* **`dependency_agent.py`**: Constructs topological edges between concepts (A depends on B).
* **`professor_agent.py`**: Powering the chat tutor, tailoring explanations according to the student's confidence levels.

**Sample code snippet (`professor_agent.py`):**
```python
async def run_professor_turn(message: str, turns: list, known_concepts: list, gap_concepts: list, paper_context: str) -> dict:
    prompt = f"""
    You are an expert academic tutor. Explain the concepts in the paper.
    Known concepts: {known_concepts}
    Concept Gaps to close: {gap_concepts}
    Paper Context: {paper_context}
    
    Answer the following question: {message}
    """
    response = await call_llm(prompt)
    return {"response": response, "confidence_signal": detect_confidence(response)}
```

---

### 4. Database Services & Storage (`app/services/`)
Wrappers around PostgreSQL (via Supabase) and Cognee to manage persistence.

* **`paper_store.py`**: CRUD operations on processed paper details, concept lists, and PDF storage paths.
* **`job_store.py`**: Tracks async tasks and progress metrics.
* **`session_store.py`**: Chat history serialization.
* **`pipeline_registry.py`**: Step-level caching allowing failed pipeline execution to resume from point of failure.
* **`topic_service.py`**: Implements topological sorting for roadmaps and Semantic Scholar crawls.

**Sample code snippet (`pipeline_registry.py`):**
```python
async def get_or_run_step(paper_id: str, step_name: str, fn, *args, **kwargs):
    step = await get_step(paper_id, step_name)
    if step and step.get("status") == "done":
        return step.get("result")

    await mark_step_running(paper_id, step_name)
    try:
        result = await fn(*args, **kwargs)
        await mark_step_done(paper_id, step_name, result)
        return result
    except Exception as exc:
        await mark_step_failed(paper_id, step_name, str(exc))
        raise exc
```

---

### 5. API Clients (`app/clients/`)
Handles raw networking and timeouts when communicating with external search systems.

* **`wikipedia_client.py`**: Fetches summaries and URLs from Wikipedia.
* **`semantic_scholar_client.py`**: Fetches papers, metadata (year, authors), and citations list.
* **`wolfram_client.py`**: Parses mathematical queries.

**Sample code snippet (`wikipedia_client.py`):**
```python
import wikipediaapi

async def fetch_summary(query: str) -> dict:
    wiki = wikipediaapi.Wikipedia('PaperMind/1.0', 'en')
    page = wiki.page(query)
    if page.exists():
        return {
            "definition": page.summary[:500],
            "url": page.fullurl
        }
    return {}
```

---

### 6. Pydantic Models (`app/models/schemas.py`)
Keeps API inputs and outputs strictly structured, isolating Cognee graph models from the REST interfaces.

**Code Pattern:**
```python
class TopicCreateRequest(BaseModel):
    seed_arxiv_id: str
    size: int = Field(default=10, ge=5, le=30)

class ConceptSummary(BaseModel):
    canonical_name: str
    display_name: str
    definition: str = ""
    category: str
    requires: list[str] = []
```

---

### 7. Core Core Infrastructure (`app/core/`)
Manages configuration loader routines and database connections.

* **`config.py`**: Parses environment variables (`SUPABASE_URL`, `OPENAI_API_KEY`).
* **`supabase_client.py`**: Instantiates global `supabase-py` client.
* **`cognee_setup.py`**: Configures local/cloud Cognee directories.
* **`auth.py`**: FastAPI user dependencies.

---

### 8. Utility & Helpers (`app/utils/`)
* **`canonical.py`**: Strips punctuation, lowercase words, and stems strings to map synonyms to a single canonical concept name (e.g., "Transformer Architectures" and "Transformers" resolve to `transformer`).

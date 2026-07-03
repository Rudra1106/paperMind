# PaperMind

> **AI-powered research paper comprehension assistant** — upload any ML/AI paper and instantly get a prerequisite knowledge map, a personalised learning roadmap, and an adaptive professor chatbot that knows exactly what you already understand.

Built for the **WeMakeDevs × Cognee Hackathon (Jun 29 – Jul 5, 2026)**.

---

## What is PaperMind?

Reading a research paper is hard not because the ideas are impossible, but because the gap between what you already know and what the paper assumes is invisible. PaperMind makes that gap explicit and navigable.

You upload a PDF. PaperMind:

1. **Extracts 15–30 concepts** the paper assumes you know, plus new ones it introduces
2. **Maps the prerequisite graph** — which concepts must be understood before others
3. **Enriches every concept** with a Wikipedia definition and resource links
4. **Writes everything into a Cognee knowledge graph** as typed `DataPoint` nodes and `Edge` objects — not loose text, structured data
5. **Shows you a topological learning roadmap** ordered by your current knowledge gaps
6. **Lets you chat with a professor** who has full access to the graph, knows your gaps, and adapts every explanation to what you actually know

As you interact — marking concepts understood, chatting, uploading more papers — your confidence scores update in real time and the roadmap re-orders itself.

---

## Demo Flow

```
Upload PDF → 8-stage pipeline runs in background → Roadmap appears
  → Mark "Confused" on attention → roadmap reprioritises
  → Open Professor Chat → "Why does multi-head attention need linear projections?"
  → Professor explains using only concepts you know
  → Confidence signal detected → score updates automatically
  → Upload second paper → overlapping concepts are reinforced
  → Knowledge Graph → visual force layout of your entire concept map
```

---

## Architecture

### The Core Insight

**Concept, not chunk, is the atomic unit.** Every other design decision flows from this.

Most RAG systems store paper chunks and retrieve them by similarity. PaperMind stores *concepts* as typed graph nodes with typed prerequisite edges. This makes the difference between:

- "Here are some chunks about attention" *(RAG)*
- "You need to understand scaled dot-product attention before you can understand multi-head attention, and here is why" *(PaperMind)*

### Two-Track Ingestion

When a paper is uploaded, two independent pipelines run concurrently (`asyncio.gather`):

**Track A — Concept extraction (selective text → LLM → graph)**
```
pdfplumber → section detection → Abstract+Intro+Methodology slice (~3000 words)
  → LLM: extract concepts + aliases (Prompt 1)
  → LLM: map prerequisite edges (Prompt 2)
  → DFS cycle validation (no LLM — code-level guard)
  → asyncio.gather: Wikipedia enrichment per concept
  → Semantic Scholar: paper-level references
  → add_data_points(): write typed ConceptNode + Edge objects into Cognee
```

**Track B — Full-text RAG indexing (parallel, independent)**
```
raw PDF bytes → cognee.remember(dataset_name=f"paper_{id}_fulltext")
  → Cognee chunks and indexes internally for chatbot similarity search
```

Track B does not need Track A's extraction results. Parallelising them cuts total processing time by ~40%.

### Two-Dataset Architecture

| Dataset | Mutation pattern | Storage strategy |
|---|---|---|
| `paper_concepts` | Append-only | `add_data_points()` — typed DataPoint/Edge, no LLM cost, local fastembed embeddings |
| `user_knowledge__<concept>` | Mutation-heavy | `forget(dataset=…)` → `remember()` per concept — each concept gets its own tiny dataset for surgical deletion |

The `paper_concepts` approach avoids redundant LLM calls: `remember()` internally runs `add + cognify + improve`, and `cognify()` calls an LLM to re-extract entities. Since we already extracted them precisely, paying for that twice would waste the entire daily OpenRouter budget on a single paper.

### Confidence Engine

Each concept's confidence lives in its own Cognee dataset (`user_knowledge__multi_head_attention`, etc). Four triggers update it:

| Trigger | Delta | Source |
|---|---|---|
| "Got it" button on roadmap | +0.30 | manual |
| "Confused" button on roadmap | −0.10 | manual |
| Professor detects "I understood X" in chat | +0.30 | chat |
| Professor detects "I'm confused about X" in chat | −0.10 | chat |
| "I already knew this" signal | set to 0.90 | chat |
| Same concept appears in a newly uploaded paper | +0.15 | paper (cross-reinforcement) |

The `forget() → remember()` update cycle is protected by a **per-concept `asyncio.Lock`**. This prevents lost updates if the chat endpoint and an `improve()` consolidation fire concurrently for the same concept during a live demo.

### Professor Agent

Every chat turn:
1. Runs three Cognee searches **concurrently**:
   - `SearchType.INSIGHTS` → structured prerequisite edges for topological context
   - `SearchType.GRAPH_COMPLETION` → synthesized explanation from the knowledge subgraph
   - `SearchType.SIMILARITY` → semantically close chunks without caring about structure
2. Builds a system prompt injecting the user's known concepts and current gap list
3. Makes **one LLM call** that returns both the explanation AND a confidence signal classification (`understood` / `confused` / `already_knew`) — halving per-turn LLM cost against the 200/day free-tier budget
4. Stores the turn in Cognee session memory (`remember(session_id=...)`) for `improve()` bridging at session end

---

## Tech Stack

### Backend

| Layer | Technology | Why |
|---|---|---|
| Web framework | **FastAPI** | Native async, automatic OpenAPI docs, clean background task pattern |
| Knowledge graph | **Cognee** (Cloud) | Typed DataPoint/Edge storage, INSIGHTS for dependency queries, GRAPH_COMPLETION for synthesis |
| LLM calls | **OpenRouter** (deepseek-chat → llama-3.1-8b → qwen-2.5-72b, all free tier) | Fallback chain; 0.2 temp for extraction, 0.65 for chat |
| PDF extraction | **pdfplumber** | Reliable text extraction with section heuristics |
| Wikipedia | **wikipedia-api** + `asyncio.to_thread` | Concurrent enrichment; wraps sync library in thread pool |
| References | **Semantic Scholar Graph API** | Paper-level citation data; no API key required |
| Config | **pydantic-settings** | Type-safe env var loading; .env file support |
| HTTP client | **httpx** | Async HTTP for OpenRouter calls with timeout + retry |

### Frontend

| Layer | Technology | Why |
|---|---|---|
| Framework | **Vite + React** | Fast HMR, simple multi-page routing |
| Routing | **React Router v7** | Client-side navigation between the 4 views |
| Styling | **Vanilla CSS** | Full design-system control via CSS custom properties |
| Knowledge graph | **Canvas API** (custom force layout) | Zero-dependency spring simulation; visually demonstrates the graph layer |
| API calls | **fetch** | Standard; Vite proxy eliminates CORS in dev |

---

## Project Structure

```
PaperMind/
├── README.md
├── backend/
│   ├── .env.example               # copy to .env and fill in your keys
│   ├── requirements.txt
│   ├── smoke_test.py              # verify Cognee Cloud connection before running
│   └── app/
│       ├── main.py                # FastAPI app factory + startup/shutdown lifecycle
│       ├── api/
│       │   └── endpoints.py       # all 6 route handlers
│       ├── core/
│       │   ├── config.py          # pydantic-settings env management
│       │   └── cognee_setup.py    # cognee.serve() cloud init + local fallback
│       ├── models/
│       │   ├── cognee_models.py   # ConceptNode DataPoint with index_fields metadata
│       │   └── schemas.py         # Pydantic API request/response models
│       ├── pipelines/
│       │   ├── pdf_pipeline.py    # text extraction + section detection + slice
│       │   ├── concept_pipeline.py# Prompt 1 + 2 + cycle validation
│       │   ├── wiki_pipeline.py   # concurrent Wikipedia enrichment
│       │   └── scholar_pipeline.py# Semantic Scholar references
│       ├── prompts/
│       │   ├── extraction.py      # concept extraction + dependency mapping prompts
│       │   └── professor.py       # professor system prompt + structured turn format
│       ├── services/
│       │   ├── llm_client.py      # call_llm + extract_json + fallback chain
│       │   ├── cognee_write.py    # write_paper_to_cognee via add_data_points
│       │   ├── confidence.py      # per-concept lock + 4 update triggers
│       │   ├── roadmap.py         # compute_gap + topological Kahn's sort
│       │   └── chat.py            # session management + Cognee context + professor turn
│       └── utils/
│           ├── canonical.py       # concept name normalization
│           └── cache_manager.py   # JSON file caching for PDFs + Wikipedia
│
└── frontend/
    ├── vite.config.js             # dev proxy to backend — no CORS in dev
    ├── package.json
    └── src/
        ├── main.jsx
        ├── App.jsx                # BrowserRouter + 4 routes
        ├── index.css              # full design system (tokens, animations, utilities)
        ├── api/
        │   └── client.js          # all fetch calls + polling utility
        ├── components/
        │   ├── Navbar.jsx/css     # sticky nav with active-link highlighting
        │   └── ConceptCard.jsx/css# concept card + pipeline progress component
        └── pages/
            ├── UploadPage.jsx/css # drag-drop + live pipeline progress polling
            ├── RoadmapPage.jsx/css# stats bar, priority filters, topological concept list
            ├── ChatPage.jsx/css   # professor chat + confidence signal sidebar
            └── GraphPage.jsx/css  # canvas force-graph + searchable concept list
```

---

## Setup

### Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- An [OpenRouter](https://openrouter.ai/) account (free tier works)
- A [Cognee Cloud](https://app.cognee.ai/) account (or run fully locally — see below)

### 1. Backend

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Open .env and fill in:
```

```bash
# Your OpenRouter API key — used for concept extraction + professor chat
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Cognee Cloud — get these from your dashboard → Connection Details
COGNEE_SERVICE_URL=https://tenant-YOUR-TENANT.aws.cognee.ai
COGNEE_API_KEY=your-x-api-key-here

# Leave blank when using Cognee Cloud — it handles LLM/embedding server-side
LLM_API_KEY=
EMBEDDING_API_KEY=
```

> **No Cognee account?** Leave `COGNEE_SERVICE_URL` blank. Cognee automatically falls back to local SQLite + LanceDB + Kuzu — zero code changes. In local mode, set `LLM_API_KEY` and `EMBEDDING_API_KEY` to your OpenRouter key.

> **On LLM/Embedding keys:** These are only needed for local Cognee mode. When `COGNEE_SERVICE_URL` is set, Cognee Cloud handles its own inference pipeline. Your `OPENROUTER_API_KEY` is separate — it's for *your own* LLM calls (concept extraction, professor chat).

### 3. Verify Cognee connection

```bash
python smoke_test.py
```

Expected: `cognee.serve() succeeded — connected to Cloud tenant` + a successful GRAPH_COMPLETION result.

### 4. Start the backend

```bash
python -m uvicorn app.main:app --reload
# API → http://127.0.0.1:8000
# Swagger docs → http://127.0.0.1:8000/docs
```

### 5. Frontend

```bash
cd ../frontend
npm install
npm run dev
# App → http://localhost:5173
```

The Vite dev server proxies all API calls to the FastAPI backend — no CORS issues in development.

---

## API Reference

All endpoints are prefixed with `/api/v1`. Full interactive docs at `http://127.0.0.1:8000/docs`.

### `POST /api/v1/upload-paper`
Upload a PDF. Returns immediately with a `job_id`. Processing runs in the background.

```json
// Response
{ "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6" }
```

### `GET /api/v1/job-status/{job_id}`
Poll this to track pipeline progress.

```json
{
  "job_id": "...",
  "status": "processing",
  "stage": "enriching_wikipedia",
  "paper_id": null,
  "error": null
}
```

**Pipeline stages (in order):**
`checking_cache` → `extracting_text` → `extracting_concepts_and_indexing` → `mapping_dependencies` → `enriching_wikipedia` → `enriching_scholar` → `writing_to_graph` → `complete`

### `GET /api/v1/roadmap/{paper_id}`
Returns the gap analysis and topologically sorted roadmap.

```json
{
  "roadmap": [
    {
      "canonical_name": "scaled_dot_product_attention",
      "display_name": "Scaled Dot-Product Attention",
      "definition": "A method of computing attention weights...",
      "category": "prerequisite",
      "confidence": 0.0,
      "priority": "critical",
      "requires": ["query_key_value_matrices"]
    }
  ],
  "total_concepts": 24,
  "known_count": 6,
  "paper_id": "..."
}
```

### `POST /api/v1/chat`
Send a message to the professor agent.

```json
// Request
{ "paper_id": "...", "session_id": "session_abc123", "message": "Explain multi-head attention" }

// Response
{
  "response": "Great question — let me build up to it from what you already know...",
  "session_id": "session_abc123",
  "confidence_signal": {
    "concept": "scaled_dot_product_attention",
    "signal_type": "understood",
    "detected_from": "I see, so the weights are..."
  }
}
```

### `POST /api/v1/concept/update`
Manually update a concept's confidence.

```json
// Request
{ "concept_name": "multi-head attention", "action": "understood" }

// Response
{ "concept_name": "multi-head attention", "new_confidence": 0.3, "action": "understood" }
```

**Actions:** `understood` (+0.30) · `confused` (−0.10) · `mastered` (set to 1.0)

### `GET /api/v1/knowledge-graph`
Returns the full user confidence map.

```json
{ "concepts": { "scaled_dot_product_attention": 0.6, "multi_head_attention": 0.3 }, "total": 24 }
```

---

## Key Design Decisions

### Why `add_data_points()` instead of `remember()` for paper concepts

`remember()` = `add() + cognify() + improve()`. `cognify()` calls an LLM to re-extract entities from whatever text you hand it. Since we already extracted concepts precisely with our own prompts, asking Cognee's internal LLM to re-derive the same structure costs the same LLM call twice — for 25 concepts per paper, that wastes the entire daily OpenRouter budget. `add_data_points()` writes typed nodes directly using only local fastembed embeddings.

### Why per-concept Cognee datasets for user knowledge

Tracking `data_id` per concept and using `forget(data_id=...)` has a real trap: `add_data_points()` creates nodes with no dataset association, so `forget(dataset=...)` silently can't find them and you need `prune_system()` (a full wipe) instead. Per-concept datasets (`user_knowledge__attention`) use the one deletion primitive that is unambiguously documented in every Cognee example. A local JSON index makes `/knowledge-graph` reads instant.

### Why Kahn's algorithm with priority tiebreaking

Plain topological sort gives *a* valid ordering. Kahn's with a priority-ordered ready queue gives the *best* ordering for a learner: prerequisites first, and among unblocked concepts, lowest-confidence-first so the learner tackles their biggest gaps earliest. The `priority_rank` dict (`critical: 0, high: 1, medium: 2, almost_there: 3`) is the only difference between a generic sort and a pedagogically sound one.

### Why one LLM call per chat turn

The initial plan called for a separate LLM call to classify confidence signals. Combining the explanation and signal detection into a single structured JSON response halves per-turn LLM cost — critical against a 200/day free-tier budget during a live demo where judges ask multiple questions.

### Why a DFS cycle guard

A cycle in the prerequisite graph crashes Kahn's algorithm. The `validate_and_break_cycles()` DFS guard runs on the LLM-returned edge list and drops the closing edge of any cycle before anything touches Cognee. Free-tier models produce cycles occasionally even when explicitly told not to.

---

## LLM Fallback Chain

```
deepseek/deepseek-chat:free
  → meta-llama/llama-3.1-8b-instruct:free
  → qwen/qwen-2.5-72b-instruct:free
```

All extraction prompts use `temperature=0.2`. Professor chat uses `temperature=0.65`.

Every LLM response goes through `extract_json()` before `json.loads()` — strips markdown fences, finds the outermost `{…}`, repairs trailing commas and common structural errors. Never assume a free-tier model returns clean JSON.

---

## Caching

Three local JSON caches in `.papermind_cache/`:

| File | Key | Prevents |
|---|---|---|
| `concepts_cache.json` | MD5 of PDF bytes | Re-processing the same paper (saves all LLM calls) |
| `wiki_cache.json` | canonical concept name | Repeated Wikipedia lookups for common concepts like "gradient descent" |
| `confidence_index.json` | canonical concept name | 50+ Cognee queries on every `/knowledge-graph` request |

Re-uploading the same PDF is instant (cache hit → skip to step 9 of the pipeline).

---

## Known Limitations

- **Single-user:** Sessions and confidence scores are not user-scoped. Multi-user would require user-namespaced Cognee datasets and a user store.
- **In-memory job store:** The `jobs` dict is process-local. A server restart loses in-flight job state. For production, use Redis or a database.
- **Section detection heuristic:** Handles ~90% of standard ML papers. Two-column layouts and non-standard headers fall back to "first 3000 words" — degrades gracefully but may produce noisier concepts.
- **Per-concept datasets at scale:** 50–150 Cognee datasets per user is fine for a demo. Thousands of concurrent users would require a different architecture.
- **Cloud vs local:** Unset `COGNEE_SERVICE_URL` to run fully locally (SQLite + LanceDB + Kuzu) — no code changes required.

---

## Hackathon Context

**Event:** WeMakeDevs × Cognee Hackathon, Jun 29 – Jul 5, 2026  
**Target categories:** Best Use of Cognee · Best Open Source

**What makes it different from a RAG wrapper:**
- Concepts, not chunks, are the atomic unit — the graph structure *is* the product
- Prerequisites are typed graph edges (`ConceptNode.requires`), not similarity-inferred
- The professor knows what you *know*, not just what you asked — personalization is structural
- `improve()` bridges ephemeral session memory into the permanent graph — Cognee's native mechanism used as designed, not worked around

---

## License

MIT

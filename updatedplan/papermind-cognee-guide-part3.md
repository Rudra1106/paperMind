# PaperMind — Cognee Deep Guide & Complex Agent Design
### Part 3: Verified API surface, Cognee Cloud/deployment setup, corrected data architecture, professor agent orchestration

Everything below is checked against docs.cognee.ai directly (quickstart, python-api reference, cognee-cloud, deploy, changelog, SearchType, custom data models) as of today. Where the docs don't spell something out precisely, I say so rather than guess — you'll do a five-minute hands-on check instead.

This supersedes: Part 1 Section 7.2 (recall routing — already patched), and meaningfully changes Part 2 Section 7.5 (confidence storage — read the new design below before building `confidence.py`).

---

## 1. The real API surface — what's actually there

Cognee 1.0 has **two layers**, and you'll use both:

**V2 memory API** (what your hackathon doc's terminology maps to, and it's real, not invented): `remember()`, `recall()`, `improve()`, `forget()`. These are high-level, convenience-wrapped operations designed for agent memory specifically.

**V1 pipeline API** (still fully available, and you'll need it for precision): `add()`, `cognify()`, `search()`, `memify()`, plus `prune.prune_data()` / `prune.prune_system()` for full resets. `remember()` is literally implemented as `add + cognify + improve` under the hood; `recall()` is `search()` with auto-routing.

**Practical rule for this project:** use `remember()` for ingestion everywhere (it's genuinely simpler and does the right thing by default), but use `search()` directly — not `recall()` — anywhere you need a *specific* retrieval strategy rather than whatever Cognee auto-picks. Auto-routing is real (there's a literal `SearchType.FEELING_LUCKY`), but your professor agent's whole value proposition depends on deliberately choosing graph-traversal vs. pure-similarity retrieval at different moments, so leave nothing to auto-routing in `professor.py`.

### 1.1 `remember()` — confirmed signature and behavior

```python
result = await cognee.remember(
    data,                      # text, file path string, http(s) URL, S3 path,
                                # a DataItem wrapper, or an UploadFile-like object
                                # (anything with .file and .filename — FastAPI's
                                # UploadFile works directly here)
    dataset_name="docs",       # NOT `dataset` — the kwarg is dataset_name
    session_id=None,           # if set: ephemeral session memory instead of permanent
    run_in_background=True,    # returns immediately; poll status separately
)
```

Two things worth building your pipeline around:

- **`remember()` accepts a FastAPI `UploadFile` directly.** For your "full paper, chunked, for the chatbot" ingestion step, you don't need to manually chunk anything — pass the uploaded PDF straight to `remember(dataset_name=f"paper_{paper_id}_fulltext")` and let Cognee's own ingestion/chunking handle it. Reserve your pdfplumber section-detection code (Part 1, Section 4.2) specifically for the *concept-extraction* step, where you genuinely need control over exactly which section text reaches your LLM prompt. Don't build a manual chunker for the chatbot's full-text RAG layer — that's redundant with something Cognee already does.
- **`run_in_background=True` + polling is a *built-in* async pattern**, not something you need to invent:

```python
result = await cognee.remember(text, dataset_name="paper_concepts", run_in_background=True)
dataset_id = result.dataset_id
status = await cognee.datasets.get_status([dataset_id])
if status.get(str(dataset_id)) == "DATASET_PROCESSING_COMPLETED":
    ...
```

This means Part 2's Section 8 job-status pattern (the one wrapping your whole upload pipeline in a custom `BackgroundTasks` job) is still correct **for the overall pipeline** — because PDF parsing, LLM concept extraction, and Wikipedia/Semantic Scholar enrichment aren't Cognee's job and still need your own async orchestration — but the *final* "write everything into Cognee" stage specifically can lean on this native background+status mechanism instead of you just blindly `await`-ing a slow call. Small win, but it means one less thing to hand-roll.

### 1.2 `search()` — the full, verified `SearchType` menu, and which ones actually fit PaperMind

This is the part worth reading carefully, because I originally guessed at two search types (`GRAPH_COMPLETION`, `SIMILARITY`) and the real menu is much richer and better-suited to what you're building than my guess was.

| SearchType | What it actually returns | Where it fits PaperMind |
|---|---|---|
| `GRAPH_COMPLETION` (default) | LLM answer grounded in a traversed subgraph + vector hints | Professor's main explanation generation — "how does X relate to Y," synthesis questions |
| `GRAPH_COMPLETION_CONTEXT_EXTENSION` | Same, but iteratively re-expands the subgraph across multiple rounds before answering | Deep prerequisite-chain questions ("what do I need before I need what I need before X") — use when a plain `GRAPH_COMPLETION` answer feels shallow |
| `INSIGHTS` | Raw relationship triples: `(source_node, relationship, target_node)`, no LLM rewriting | **This is your dependency-mapping retrieval, not GRAPH_COMPLETION.** When the roadmap generator needs "what does concept X require," `INSIGHTS` gives you exact structured edges you can feed straight into your topological sort — more reliable than parsing an LLM's prose answer |
| `TRIPLET_COMPLETION` | Retrieval using extracted (subject, predicate, object) triples specifically | Alternative to `INSIGHTS` for factual/relationship lookups; worth A/B-testing against `INSIGHTS` for your gap-analysis queries on Day 1-2 |
| `SIMILARITY` | Pure vector nearest-neighbor, no graph traversal | When the professor needs "explain positional encoding" without caring about structure — pulls semantically close chunks |
| `CHUNKS` | Raw original text passages, no LLM rewriting | Citing exact paper text back to the learner, or debugging what got ingested |
| `SUMMARIES` | Pre-generated document/concept summaries | Quick concept definitions for the roadmap UI, cheaper than a full `GRAPH_COMPLETION` call |
| `RAG_COMPLETION` | Classic chunk-retrieve-then-generate, no graph structure | Fallback if `GRAPH_COMPLETION` output quality is inconsistent on the free-tier LLM mid-week |
| `CYPHER` / `NATURAL_LANGUAGE` | Direct or inferred Cypher query against the graph | Only if you want to hand-write a precise topological query yourself instead of trusting a retriever — probably unnecessary for a 7-day build, but good to know it exists if `INSIGHTS` doesn't give you clean enough edges |
| `FEEDBACK` | Attaches feedback text to the most recent search interaction | **This replaces part of your custom confidence-signal detection.** See 3.3 below. |
| `FEELING_LUCKY` | Auto-selects a search type | Don't use this in `professor.py` — you want deliberate control, not auto-routing, given personalization is the whole product |

Revised `professor.py` context-builder, using the right search type per purpose instead of my earlier two-type guess:

```python
from cognee import search, SearchType

async def build_professor_context(paper_id: str, question: str) -> dict:
    prereq_edges = await search(
        query_text=question,
        query_type=SearchType.INSIGHTS,          # structured edges, not prose
        datasets=["paper_concepts"],
    )
    explanation = await search(
        query_text=question,
        query_type=SearchType.GRAPH_COMPLETION,   # grounded LLM answer
        datasets=["paper_concepts"],
        save_interaction=True,                     # needed for FEEDBACK, see 3.3
    )
    known_concepts = await search(
        query_text="concepts with confidence above 0.6",
        query_type=SearchType.INSIGHTS,
        datasets=["user_knowledge"],
    )
    return {"prereq_edges": prereq_edges, "explanation": explanation, "known_concepts": known_concepts}
```

**Verify on Day 1, don't assume:** the exact set of `SearchType` values available depends on your installed version — `dir(SearchType)` in a REPL is the actual source of truth, not this table. The table above is drawn from multiple current doc pages so it should hold, but a five-second check removes all doubt before you build `professor.py` around it.

---

## 2. `forget()` — corrected, with a cleaner design than Part 2 proposed

Real signature, confirmed via CLI (which mirrors the Python API 1:1 per Cognee's own docs) and the Custom Data Models page:

```python
await cognee.forget(dataset="onboarding")                    # wipe one dataset
await cognee.forget(dataset="onboarding", data_id=some_uuid)  # wipe one item (CLI-confirmed; verify Python kwarg name matches on Day 1)
await cognee.forget(everything=True)                          # wipe everything for current user
```

Part 2 proposed tracking a `data_id` per concept locally so you could `forget()` precisely by id. **That works, but it has a real gotcha worth avoiding:** if you ever use `add_data_points()` directly for custom DataPoints (which Part 1 Section 2.4 suggested for confidence scores), those nodes are inserted with **no dataset association at all** unless you route them through `run_custom_pipeline()` with a `PipelineContext` — and without that association, `forget(dataset=...)` silently won't find them; you'd need `prune_system()` instead, which is a full wipe, not a surgical one. That's a real trap for a hackathon timeline: building the custom-DataPoint confidence model, discovering on Day 5 that your "surgical" deletes are actually no-ops, and not having time left to fix it properly.

**Cleaner design, using only what's directly documented and demonstrated repeatedly (dataset-level forget):** give every concept its own tiny dataset inside `user_knowledge`, named by canonical key —

```python
def user_knowledge_dataset_name(canonical_concept: str) -> str:
    return f"user_knowledge__{canonical_concept}"

async def update_confidence(concept_name: str, delta: float | None = None,
                              set_value: float | None = None, source: str = "chat") -> float:
    canonical_name = canonical(concept_name)
    dataset = user_knowledge_dataset_name(canonical_name)
    async with _concept_locks[canonical_name]:
        current = await get_current_confidence(canonical_name)
        new_value = set_value if set_value is not None else max(0.0, min(1.0, current + delta))

        await cognee.forget(dataset=dataset)  # wipes exactly this concept's one-item dataset
        await cognee.remember(
            format_user_knowledge_ingestion(canonical_name, new_value, source),
            dataset_name=dataset,
        )
        return new_value
```

This sidesteps `data_id` tracking entirely — no local id map to keep in sync, no risk of the standalone-DataPoint dataset-association gotcha, and it only relies on the one deletion primitive that's unambiguously documented and shown working in every real Cognee example (`forget(dataset="main_dataset")`, `forget(dataset="onboarding")`). The lock-per-concept pattern from Part 2 is unchanged and still needed for the same race-condition reason.

**Trade-off, stated honestly:** you'll end up with potentially 50-150 tiny datasets (one per concept the user has ever touched a confidence score for). Cognee is explicitly built to handle arbitrary numbers of datasets, so this isn't abusing the system — but it does mean a query like "give me every concept the user knows" can't be a single `search(datasets=["user_knowledge"])` call anymore, since there's no single `user_knowledge` dataset. You'll need `cognee.datasets.list()` (or the equivalent) filtered by the `user_knowledge__` prefix, then either query each mini-dataset or maintain a lightweight local index (a JSON file mapping `canonical_name -> current_confidence`, updated on every `update_confidence()` call, purely for fast reads — Cognee remains the source of truth, the JSON file is just a read cache so `/knowledge-graph` and the roadmap endpoint aren't doing 50+ Cognee calls on every request). That local cache is a five-line addition, not a real complication.

If, after trying this on Day 1, the per-concept-dataset approach feels too fiddly in practice, the fallback is: keep a single `user_knowledge` dataset and accept `forget(dataset="user_knowledge")` as an occasional full-wipe-and-rebuild-from-a-local-snapshot operation rather than a per-concept surgical delete. That's a legitimate hackathon-scope simplification — flag it as a known limitation in your README rather than spending a day building a more precise mechanism the judging criteria don't require.

---

## 3. Native mechanisms that replace custom code from Parts 1-2

Three places where Cognee already does something you were about to hand-roll:

### 3.1 Session memory — replaces the custom `ChatSession` persistence idea

```python
await cognee.remember(user_message, session_id=session_id)         # ephemeral, fast
results = await cognee.recall(query_text=followup, session_id=session_id)  # session-aware
await cognee.improve(dataset="user_knowledge", session_id=session_id)      # bridge to permanent
```

`recall()` with a `session_id` checks session cache first, falls through to the permanent graph if needed — this is real, documented behavior, not a guess. Use this for the running professor conversation instead of hand-rolling JSON snapshotting. You still want a small local list for formatting the actual system-prompt conversation history (Cognee's session store isn't going to hand you back a chat-formatted transcript), but don't build your own crash-safety persistence for it — session memory already survives independently of your FastAPI process.

### 3.2 `remember()`'s built-in background+status — already covered in 1.1, don't rebuild it for the Cognee-writing stage of your pipeline.

### 3.3 `FEEDBACK` search type — a real alternative to custom chat-engagement detection

Part 1's Section 7.4 asked your extraction LLM to classify, on every turn, whether the learner's message was a confidence signal. That's still the right approach for explicit signals ("I understood this"). But Cognee has a *native* feedback mechanism worth layering in for the "did this explanation land" signal specifically:

```python
# after generating an explanation with save_interaction=True (see 1.2's example)
await search(
    query_text="This explanation was helpful and clear",   # or negative phrasing
    query_type=SearchType.FEEDBACK,
    last_k=1,  # applies to the most recent saved interaction
)
```

Cognee associates the feedback with the specific graph paths that produced that answer and reweights them over repeated use — genuinely closer to your "chat engagement bumps confidence" trigger than anything you'd build yourself, and it's a legitimate way to demonstrate `improve()`-adjacent sophistication to judges without extra prompt-engineering work. Practical scope call: **use your Section 7.4 LLM-classification for the primary "understood/confused/already knew" signals** (you need that regardless, for the explicit `/concept/update` endpoint), and treat `FEEDBACK`+`save_interaction` as an optional Day-5-or-later enhancement if time remains, not a Day-1 requirement.

---

## 4. Cognee Cloud & Deployment — setup guidance for your actual credits

Confirmed pattern for connecting to Cognee Cloud from the same `cognee` package you'd use locally — there's no separate cloud SDK to learn:

```python
import cognee

await cognee.serve(
    url="https://your-tenant.aws.cognee.ai",   # from your Cognee Cloud console
    api_key="your-api-key",                     # from the API Keys page in the console
)

# from here, remember/recall/improve/forget all route to your cloud tenant
await cognee.remember("...", dataset_name="paper_concepts")
results = await cognee.recall("...")

await cognee.disconnect()   # closes the connection; credentials stay cached for next time
```

Or via env vars, which is the better fit for your `.env`-driven config approach — this is what makes the local/cloud switch a one-line change as planned in Part 1:

```bash
# .env — Cognee Cloud mode
COGNEE_SERVICE_URL="https://your-tenant.aws.cognee.ai"
COGNEE_API_KEY="ck_..."
```

```python
# cognee_setup.py
import os
import cognee

async def init_cognee():
    if os.getenv("COGNEE_SERVICE_URL"):
        await cognee.serve()   # reads COGNEE_SERVICE_URL / COGNEE_API_KEY automatically
    else:
        # local mode: no serve() call needed, Cognee defaults to local SQLite+LanceDB+Kuzu
        pass
```

For the actual "Best Open Source" submission, unset those two env vars and Cognee falls back to the local file-based stack by default — no code change required, confirming the config-driven approach from Part 1 is sound. One thing worth doing once, early: run through Cognee's own **Deploy REST API Server** guide (`cognee.serve()` server-side, not client-side — i.e., running your *own* Cognee instance behind a REST API rather than connecting to Cognee Cloud) is a *separate* concept from what you need here. You don't need to self-host a REST API server for this hackathon — Cognee Cloud already gives you the managed server, and local mode runs in-process without any server at all. Skip that deployment guide's server-hosting content; it's for a different use case (exposing Cognee as a service to other consumers) than yours (your FastAPI app calling Cognee as a library, either against local files or against the cloud).

---

## 5. Custom Data Models — the real pattern, corrected

Part 1's Section 2.4 sketched a generic dataclass. The real, documented pattern is richer and worth knowing even though Section 2's recommendation above (per-concept-dataset text ingestion) sidesteps needing it for confidence scores specifically. You may still want this for dependency edges, where precise, typed relationships matter more than a text-extracted guess:

```python
from cognee.infrastructure.engine import DataPoint
from cognee.infrastructure.engine.models.Edge import Edge
from cognee.tasks.storage import add_data_points
from typing import Any
from pydantic import SkipValidation

class Concept(DataPoint):
    name: str
    definition: str
    requires: SkipValidation[Any] = None   # single Concept or list[Concept]
    metadata: dict = {"index_fields": ["name", "definition"]}  # these fields get embedded for search

async def ingest_concept_graph(concepts: list[dict]):
    nodes = {c["canonical_name"]: Concept(name=c["canonical_name"], definition=c["definition"]) for c in concepts}
    for c in concepts:
        node = nodes[c["canonical_name"]]
        prereqs = [nodes[p] for p in c.get("requires", []) if p in nodes]
        if prereqs:
            # Edge lets you attach a relationship_type and weight — precise, typed,
            # not left to an LLM's guess about what verb to use
            node.requires = (Edge(relationship_type="requires", weight=1.0), prereqs) if len(prereqs) > 1 \
                else (Edge(relationship_type="requires", weight=1.0), prereqs[0])
    await add_data_points(list(nodes.values()))
```

`metadata = {"index_fields": [...]}` controls exactly which fields get embedded for `SIMILARITY`/`GRAPH_COMPLETION` search — worth setting deliberately rather than letting Cognee guess, since your definitions are the fields learners will actually query against.

**Repeat of the important caveat from Section 2:** standalone `add_data_points()` calls (as shown above) create nodes with no dataset tag, so `forget(dataset=...)` can't clean them up individually — full removal requires `prune_system()`. If you use this pattern for `paper_concepts` (which is largely append-only and rarely needs deletion anyway, per Part 1's original observation), that's a non-issue. Don't use standalone `add_data_points()` for anything in `user_knowledge`, where precise deletion is the whole point — that's exactly why Section 2's per-concept-dataset text-ingestion design is the safer choice there.

---

## 6. Day-1 smoke test — run this before writing any pipeline code

```python
# smoke_test.py — confirms every assumption in this document against your actual install
import asyncio
import cognee
from cognee import search, SearchType

async def main():
    print("SearchType values available:", [s.name for s in SearchType])

    await cognee.forget(everything=True)  # clean slate

    result = await cognee.remember(
        "The concept 'multi-head attention' requires prior understanding of "
        "'scaled dot-product attention'. Scaled dot-product attention is defined as "
        "a method of computing attention weights using query, key, and value matrices.",
        dataset_name="smoke_test_paper_concepts",
    )
    print("remember() returned:", result)
    print("Does it have a data_id field?", hasattr(result, "data_id"))

    insights = await search(
        query_text="multi-head attention prerequisites",
        query_type=SearchType.INSIGHTS,
        datasets=["smoke_test_paper_concepts"],
    )
    print("INSIGHTS result shape:", insights)

    graph_answer = await search(
        query_text="what does multi-head attention require?",
        query_type=SearchType.GRAPH_COMPLETION,
        datasets=["smoke_test_paper_concepts"],
    )
    print("GRAPH_COMPLETION result:", graph_answer)

    # test dataset-level forget precision
    await cognee.forget(dataset="smoke_test_paper_concepts")
    post_forget = await search(
        query_text="multi-head attention",
        query_type=SearchType.CHUNKS,
        datasets=["smoke_test_paper_concepts"],
    )
    print("After forget, should be empty:", post_forget)

if __name__ == "__main__":
    asyncio.run(main())
```

Run this against Cognee Cloud first (fastest to get unblocked), read the printed output for the three things this whole document flagged as unverified — the exact `SearchType` enum members, whether `remember()`'s return object exposes anything id-like, and what `INSIGHTS` output actually looks like structurally (you'll need to know its shape to feed it into your topological sort). Fifteen minutes here saves rework in Sections 5-7 of Part 1 and Part 2.

---

That's the Cognee layer, fully grounded. Want me to now revisit the FastAPI endpoint code in Part 2 to match the `dataset_name` kwarg correction and the per-concept-dataset confidence design, or move on to something else — the concept-extraction/PDF pipeline code, or the Streamlit frontend?

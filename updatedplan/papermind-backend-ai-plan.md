# PaperMind — Backend & AI Implementation Plan
### Part 1 of the build plan: Cognee data layer, OpenRouter/LLM pipeline, gap analysis, professor agent, FastAPI backend
### For the WeMakeDevs × Cognee Hackathon (Jun 29 – Jul 5, 2026)

---

## 0. Reading your own plan — what's already right, what needs sharpening

Your overview and mental-model docs get the hard part right: **concept, not paper or chunk, is the atomic unit.** That single decision is what separates PaperMind from every RAG-wrapper submission in this hackathon. Everything below is built to protect that decision.

Four things in the original plan need sharpening before you write code, because they'll bite you mid-week if left implicit:

1. **"remember() with guided text" is underspecified.** You need to know, before Day 1, exactly what string format you're feeding Cognee so its internal LLM extracts the relationship types you want, every time. Section 2 gives you the exact templates.
2. **Free-tier OpenRouter models are flaky.** `deepseek/deepseek-chat:free` will occasionally return malformed JSON, time out, or hit a shared rate limit that isn't just "your" 200/day — it's a shared free pool that gets slow under load. You need a fallback model chain and JSON-repair logic from Day 1, not Day 5 when you're debugging under time pressure. Section 3 covers this.
3. **Confidence updates via forget()+remember() is a race-condition risk** if your chat endpoint and your confidence endpoint can fire concurrently in a demo. Section 7 gives you a locking pattern that costs almost nothing to build now.
4. **The "5 endpoints" are stated as REST but paper processing is inherently async** (PDF parse → LLM extraction → Wikipedia → Semantic Scholar → Cognee writes, easily 15-30 seconds). You need a job-status pattern from Day 1 or your Streamlit UI will hang or you'll bolt on polling in a panic on Day 6. Section 8 gives you the exact pattern.

Cognee Cloud vs local, addressed once: your hackathon targets "Best Open Source," which needs the local SQLite+LanceDB+Kuzu stack for the actual submission. But local graph-DB setup (native Kuzu bindings, LanceDB) is a classic first-day timesink on unfamiliar machines. Since you have Cognee Cloud credits, **develop against cloud all week, and keep every Cognee call behind a thin `cognee_setup.py` config layer** so switching to local is one `.env` change on Day 6-7 before you record the demo. If cloud proves reliable enough for the actual demo video, you even have the option to reconsider targeting "Best Cognee Cloud" instead — decide that on Day 6, not now. Don't let this decision block Day 1.

---

## 1. The mental model, made executable

A **concept** is the only first-class object with meaning. Papers, users, chat sessions, Wikipedia pages — all of them exist only to attach data *to* a concept or to record a *relationship between* concepts. When you're stuck mid-build on where a piece of data should live, ask: "is this a property of a concept, a property of a user's relationship to a concept, or an edge between two concepts?" There's no fourth category in this system. That discipline is what keeps the graph from fragmenting.

Two datasets, two different mutation patterns:
- `paper_concepts` — append-only in practice. You rarely delete domain knowledge; a concept's definition doesn't become false. New papers add new concepts and new edges.
- `user_knowledge` — mutation-heavy. Confidence scores change constantly, on every chat turn, every "I understood X," every session. This dataset needs the delete-then-reinsert pattern (`forget()` → `remember()`) because Cognee's node model doesn't give you an in-place numeric-field update — you're replacing a fact, not editing one.

Keep this asymmetry in your head; it's why the two datasets need different code paths even though they share a schema shape.

---

## 2. Cognee Data Architecture — exact schemas and ingestion templates

### 2.1 The concept node — full field list

Every concept, regardless of which dataset it lives in, carries:

| Field | Type | Source |
|---|---|---|
| `canonical_name` | string | derived via normalization function, this is the graph key |
| `display_name` | string | original casing as first seen, for UI |
| `definition` | string | Wikipedia summary, 2-3 sentences |
| `first_seen_paper` | string | paper_id that introduced it |
| `prerequisite_of` | list[string] | edges: this concept is required by X |
| `requires` | list[string] | edges: this concept requires Y |
| `resource_urls` | list[string] | Wikipedia references + Semantic Scholar citation |

`user_knowledge` entries add:

| Field | Type | Source |
|---|---|---|
| `confidence` | float 0.0-1.0 | confidence engine, Section 7 |
| `last_updated` | ISO date | system clock at write time |
| `update_source` | enum | `paper` \| `chat` \| `manual` \| `improve_consolidation` |

### 2.2 Canonical normalization — write this first, before any pipeline code

```python
# knowledge/canonical.py
import re

def canonical(name: str) -> str:
    """
    Every concept, from any source (paper extraction, Wikipedia link,
    chat mention), must pass through this before touching Cognee.
    This is the single point of truth that prevents graph fragmentation.
    """
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)          # strip punctuation
    s = re.sub(r"[\s-]+", "_", s)            # spaces/hyphens -> underscore
    return s

# "Multi-Head Attention" -> "multi_head_attention"
# "multi head attention"  -> "multi_head_attention"
# "MHA (multi-head attn.)" -> "mha_multihead_attn"  <-- acronyms are the one gap
```

Acronyms are the one real gap in pure string normalization — "MHA" and "multi_head_attention" won't collide automatically. Handle this with a small **alias table** rather than trying to make normalization smarter: when the concept extraction prompt (Section 4) returns a concept, also ask it for `"aliases": ["MHA"]` in the same JSON call, and store a `canonical_name -> [aliases]` lookup in a local JSON file (`.papermind_cache/alias_map.json`). Before creating any new concept node, check the alias map first, not just the canonical function. This is 15 minutes of work on Day 1 that saves you a duplicate-node bug you won't have time to chase on Day 4.

### 2.3 Guided text ingestion — Option A, exact templates

This is the piece your overview plan gestures at but doesn't specify. Cognee's `remember()` runs its own extraction LLM over whatever text you hand it, so the *shape* of your input text directly determines the *shape* of the graph you get back. Use consistent, formulaic sentences — don't write natural prose, write templated statements that always use the same verb for the same relationship type, so Cognee's extractor learns a consistent pattern within a session.

**Ingesting a concept with its prerequisites (paper_concepts dataset):**
```python
def format_concept_ingestion(concept: dict, paper_id: str) -> str:
    name = concept["canonical_name"]
    lines = [f"The concept '{name}' is defined as: {concept['definition']}"]
    for prereq in concept.get("requires", []):
        lines.append(f"The concept '{name}' requires prior understanding of '{prereq}'.")
    lines.append(f"The concept '{name}' was introduced or used in the paper '{paper_id}'.")
    for url in concept.get("resource_urls", [])[:3]:
        lines.append(f"A learning resource for '{name}' is available at {url}.")
    return "\n".join(lines)
```

**Ingesting a user_knowledge fact:**
```python
def format_user_knowledge_ingestion(concept_name: str, confidence: float, source: str) -> str:
    return (
        f"Concept: {concept_name}. "
        f"Confidence: {confidence:.2f}. "
        f"Last updated: {datetime.utcnow().date().isoformat()}. "
        f"Source: {source}."
    )
```

Notice this second template is deliberately closer to structured data than prose — because `user_knowledge` facts don't need relationship extraction (a confidence score has no edges of its own), you're mainly using Cognee here as a queryable store, not for its relationship-extraction strength. This is exactly why Section 2.4's custom data model is the better fit for confidence, and text ingestion is a fallback if you run short on time.

### 2.4 Custom data models — Option B, for confidence scores specifically

Numeric fields that need precise updates are a bad fit for LLM-mediated text extraction (the extractor might round, misread, or drop the number). Use Cognee's `add_data_points()` with a dataclass for anything numeric:

```python
# knowledge/data_models.py
from dataclasses import dataclass
from datetime import date

@dataclass
class UserConceptKnowledge:
    concept_name: str      # canonical
    confidence: float
    last_updated: str      # ISO date
    update_source: str     # paper | chat | manual | improve_consolidation
    paper_id: str | None = None
```

This gives you deterministic reads and writes for the one field (`confidence`) that the whole product's personalization hinges on. Reserve guided-text ingestion (2.3) for definitions, relationships, and resources — anything relationship-shaped, not number-shaped. If you're tight on time by Day 2, it is acceptable to fall back to text-only ingestion for everything and accept slightly noisier confidence retrieval — but budget a half-day for the custom data model if you can, because a demo where the confidence score visibly drifts wrong in front of judges is worse than a demo with one fewer feature.

---

## 3. OpenRouter / LLM Integration Layer

### 3.1 Model chain, not a single model

`deepseek/deepseek-chat:free` is your primary, but free-tier models on OpenRouter share load across all their free users, not just your 200/day allocation — under load they slow down or occasionally 429. Build a small ordered fallback chain from Day 1:

```python
# pipelines/llm_client.py
MODEL_CHAIN = [
    "deepseek/deepseek-chat:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]
```

Verify the exact current free-model slugs against OpenRouter's live model list before you hardcode this — free-tier model availability changes. The point isn't these specific three; it's that your client function tries the next model in the chain on failure rather than crashing the pipeline.

```python
import httpx, json, time

async def call_llm(prompt: str, system: str = "", max_retries_per_model: int = 2) -> str:
    for model in MODEL_CHAIN:
        for attempt in range(max_retries_per_model):
            try:
                resp = await httpx.AsyncClient(timeout=30).post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
                    json={
                        "model": model,
                        "messages": ([{"role": "system", "content": system}] if system else [])
                                    + [{"role": "user", "content": prompt}],
                        "temperature": 0.2,   # low temp: extraction tasks need consistency, not creativity
                    },
                )
                if resp.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError):
                continue
        # this model exhausted its retries, fall to next model in chain
    raise RuntimeError("All models in fallback chain failed")
```

Temperature 0.2 across all extraction/classification prompts (concept extraction, dependency mapping, gap roadmap, confidence classification) — you want the same paper to produce close to the same concept list on a re-run, both for the cache to actually hit and for your Day-3 verification checks to be meaningful. Reserve higher temperature (0.6-0.7) only for the professor chatbot's actual explanations, where some variation in phrasing is fine and even desirable.

### 3.2 JSON reliability — the thing that will actually break your demo

Free models, even instructed to "return ONLY JSON," will sometimes wrap it in markdown fences, add a stray sentence before it, or produce a trailing comma. Never `json.loads()` a raw model response directly. Every JSON-expecting call goes through:

```python
def extract_json(raw: str) -> dict:
    # strip markdown fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    # grab the outermost {...} in case of preamble/postamble text
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model output")
    candidate = raw[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # one repair attempt: trailing commas are the most common free-model failure
        repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
        return json.loads(repaired)
```

If this still fails after the repair attempt, that's your signal to retry the LLM call itself (a fresh generation, not a repair of the same bad output) rather than trying to parse harder. Two failed parses on the same prompt → fall to the next model in the chain.

### 3.3 Rate-limit budget accounting

You estimated 20-30 calls per paper with caching. Make this a real, visible number, not an estimate you hope holds:

```python
# cache/rate_tracker.py — trivial but worth having visible in your demo/README
class RateTracker:
    def __init__(self, daily_limit=200):
        self.daily_limit = daily_limit
        self.used_today = self._load()

    def record(self):
        self.used_today += 1
        self._save()

    def remaining(self):
        return self.daily_limit - self.used_today
```

Surface `remaining()` in a small debug endpoint or Streamlit sidebar during development — you want to *see* the number dropping while you test, not discover on Day 4 that a debugging loop burned your whole daily allocation testing one paper.

---

## 4. Concept Extraction & Dependency Mapping Pipeline

### 4.1 Full pipeline sequence

1. PDF → pdfplumber full text extraction
2. Section detection via header-matching heuristic (Section 4.2)
3. Selective slice: Abstract + Introduction + Methodology only, capped ~3000 words
4. Cache check: MD5 of PDF bytes → if hit, skip straight to step 8
5. Concept extraction LLM call (Prompt 1, Section 4.3)
6. Dependency mapping LLM call (Prompt 2, using the concept list from step 5 as input)
7. Alias/canonical resolution against the local alias map (Section 2.2)
8. Wikipedia enrichment per concept (Section 5 detail — parallelized, not sequential, since it's free API calls with no shared rate limit)
9. Semantic Scholar enrichment for the paper's own references
10. Guided-text ingestion into `paper_concepts` (templates from Section 2.3)
11. Cache write: paper hash → full concept+dependency result, so re-uploads are instant

### 4.2 Section detection — the heuristic, concretely

```python
SECTION_HEADERS = [
    "abstract", "introduction", "related work", "background",
    "methodology", "method", "approach", "architecture",
    "experiments", "results", "evaluation", "discussion",
    "conclusion", "references", "acknowledgments",
]

def detect_sections(pages_text: list[str]) -> dict[str, str]:
    """
    Walk lines; a line is a section header if, after stripping numbering
    and whitespace, its lowercased form matches (or closely matches) a
    known header AND it's short (<6 words) AND the next line isn't also
    a short all-caps line (avoids matching stray title-case sentences).
    """
    full_text = "\n".join(pages_text)
    lines = full_text.split("\n")
    sections, current = {}, "preamble"
    sections[current] = []
    for line in lines:
        stripped = re.sub(r"^\d+[\.\)]?\s*", "", line.strip()).lower()
        if len(stripped.split()) <= 5 and stripped in SECTION_HEADERS:
            current = stripped
            sections[current] = []
        else:
            sections[current].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}
```

This is intentionally simple — your own docs correctly note this doesn't need a fancy NLP model. Budget for the fact that ~10% of papers (unusual formatting, two-column layouts pdfplumber mangles, non-standard section names) will fail this heuristic. **Fallback: if fewer than 3 recognizable sections are found, just take the first 3000 words of the full text.** This degrades gracefully instead of crashing the pipeline — important because your demo paper choice matters less if the pipeline doesn't hard-fail on an unexpected upload during Q&A.

### 4.3 Prompt 1 — Concept Extraction, full text

```xml
<instructions>
You are analyzing a research paper to build a prerequisite knowledge map
for a learner. Extract every distinct technical concept a learner must
understand to comprehend this paper's core contribution.

Be granular: prefer "gradient descent with momentum" over "machine learning".
Prefer "scaled dot-product attention" over "attention".
Aim for 15-30 concepts for a typical paper — fewer than 10 is usually too
coarse, more than 40 is usually too granular to be useful.

For each concept, also provide any common aliases or abbreviations used
in the paper itself (e.g. "MHA" for "multi-head attention").

Think step by step: first identify the paper's core contribution, then
work backward to identify what a reader must already know to follow that
contribution, then identify what the paper itself teaches as new.
</instructions>
<paper_content>
{abstract_intro_methodology}
</paper_content>
<output_format>
Return ONLY a JSON object inside <output> tags, no text before or after:
<output>
{
  "paper_title": "...",
  "core_contribution": "one sentence describing what's novel here",
  "concepts": [
    {
      "name": "scaled dot-product attention",
      "aliases": ["SDPA"],
      "category": "prerequisite" or "introduced",
      "brief_context": "how this concept is used in the paper, one sentence"
    }
  ]
}
</output>
</output_format>
```

The `category: prerequisite | introduced` field matters more than it looks — it's what lets your roadmap generator (Section 6) distinguish "you need to know this before reading" from "this paper will teach you this," which is exactly the distinction that makes your gap analysis feel intelligent rather than a flat keyword list.

### 4.4 Prompt 2 — Dependency Mapping

```xml
<instructions>
Given this list of technical concepts extracted from a research paper,
build a directed prerequisite graph. For each concept, list which OTHER
concepts from this same list it depends on — i.e., which ones must be
understood first.

Only use concepts from the provided list. Do not invent new concepts here.
A concept with no prerequisites from this list should have an empty array.
Avoid cycles: if you find yourself wanting to say A requires B and B
requires A, choose the more fundamental one as the prerequisite.
</instructions>
<concept_list>
{json_list_of_concept_names}
</concept_list>
<output_format>
Return ONLY JSON inside <output> tags:
<output>
{
  "edges": [
    {"concept": "multi-head attention", "requires": ["scaled dot-product attention", "linear projections"]}
  ]
}
</output>
</output_format>
```

**Cycle validation is your job, not the model's** — the prompt asks the model to avoid cycles, but free models will occasionally still produce one. Run a cheap cycle check (DFS with a visited/in-progress set) on the returned edge list before writing anything to Cognee. If a cycle is found, break it by dropping the edge that has the lower co-occurrence with "prerequisite"-category concepts — or, simplest for hackathon time constraints, just drop the second edge encountered in the cycle and log it. Don't let a cycle reach your topological sort in Section 6; that will crash the roadmap generator at demo time, which is the single worst place for this bug to surface.

---

## 5. Wikipedia + Semantic Scholar Enrichment (concurrent, not sequential)

Run these two enrichment calls **concurrently per concept**, since neither shares your OpenRouter rate limit and both are pure I/O wait:

```python
import asyncio

async def enrich_concept(concept_name: str) -> dict:
    wiki_task = asyncio.create_task(fetch_wikipedia(concept_name))
    # scholar enrichment only for a subset — see note below
    wiki_result = await wiki_task
    return wiki_result
```

For a paper with 20-30 concepts, running Wikipedia lookups concurrently rather than sequentially is the difference between a 3-second enrichment step and a 20-second one — this matters for your demo's "10 seconds" claim in the demo story. Use `asyncio.gather()` over all concepts at once:

```python
async def enrich_all(concept_names: list[str]) -> dict[str, dict]:
    results = await asyncio.gather(
        *[fetch_wikipedia(name) for name in concept_names],
        return_exceptions=True,
    )
    return {
        name: (result if not isinstance(result, Exception) else {"definition": None, "resources": []})
        for name, result in zip(concept_names, results)
    }
```

`return_exceptions=True` is important: a single concept with no matching Wikipedia page (common for very new or very niche terms) must not take down the whole enrichment batch. Missing Wikipedia data should degrade to "no definition available yet" in the graph, not an exception that aborts the paper upload.

Semantic Scholar enrichment (Section 6 of your own doc) is lower priority for concurrency — it's used mainly at the *paper* level (one call for the paper's own references) rather than per-concept, so it's naturally cheap. Only add per-concept Semantic Scholar lookups (searching for the canonical paper about a concept) if you have time budget left after Day 3; it's a nice-to-have resource-richness feature, not core to the gap analysis.

---

## 6. Gap Analysis & Roadmap Generation

### 6.1 The algorithm, precisely

```python
def compute_gap(paper_concepts: list[dict], user_knowledge: dict[str, float], threshold=0.6) -> list[dict]:
    gap = []
    for concept in paper_concepts:
        name = concept["canonical_name"]
        confidence = user_knowledge.get(name, 0.0)
        if confidence < threshold:
            priority = (
                "critical" if confidence == 0.0 else
                "high" if confidence < 0.4 else
                "medium" if confidence < 0.59 else
                "almost_there"
            )
            gap.append({**concept, "confidence": confidence, "priority": priority})
    return gap
```

### 6.2 Topological ordering with priority as a tiebreaker

Plain topological sort (Kahn's algorithm) gives you *a* valid ordering, but you want the *best* one for a learner — prerequisites first, and within concepts that have no ordering constraint between them, lowest-confidence-first so the learner tackles their biggest gaps earliest:

```python
from collections import deque

def topological_roadmap(gap_concepts: list[dict], edges: dict[str, list[str]]) -> list[dict]:
    names = {c["canonical_name"] for c in gap_concepts}
    in_degree = {n: 0 for n in names}
    graph = {n: [] for n in names}

    for concept_name, prereqs in edges.items():
        if concept_name not in names:
            continue
        for prereq in prereqs:
            if prereq in names:
                graph[prereq].append(concept_name)
                in_degree[concept_name] += 1

    priority_rank = {"critical": 0, "high": 1, "medium": 2, "almost_there": 3}
    by_name = {c["canonical_name"]: c for c in gap_concepts}

    # ready = zero in-degree, sorted by priority so we pick the most-needed
    # concept first among all currently-unblocked ones
    ready = deque(sorted(
        [n for n in names if in_degree[n] == 0],
        key=lambda n: priority_rank[by_name[n]["priority"]],
    ))

    ordered = []
    while ready:
        current = ready.popleft()
        ordered.append(by_name[current])
        newly_ready = []
        for neighbor in graph[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                newly_ready.append(neighbor)
        # re-sort insertions by priority to keep the queue priority-ordered
        ready = deque(sorted(list(ready) + newly_ready,
                              key=lambda n: priority_rank[by_name[n]["priority"]]))

    return ordered
```

This is the "real graph reasoning" your doc correctly flags as a differentiator — make sure your Day 3 verification check actually confirms no concept appears before its prerequisite in the output list, not just that the function runs without error.

---

## 7. Professor Chatbot — Agentic Orchestration

### 7.1 Session state design

A chat session needs, in memory (not yet in Cognee — that's what `improve()` is for at session end):

```python
@dataclass
class ChatSession:
    session_id: str
    paper_id: str
    user_id: str = "default"          # single-user demo, but keep the field
    turns: list[dict] = field(default_factory=list)   # [{"role", "content"}]
    concepts_discussed: set[str] = field(default_factory=set)
    pending_confidence_signals: list[dict] = field(default_factory=list)
```

Keep this in an in-memory dict keyed by `session_id` for the hackathon (no need for Redis) — but write it to a local JSON snapshot after every turn so a server restart mid-demo doesn't lose the session. This is a 10-line safety net that's cheap insurance against your worst possible demo-day failure mode.

### 7.2 recall() injection strategy — CORRECTED (verified against Cognee docs)

**Update:** `recall()`'s auto-routing is real (there's a `SearchType.FEELING_LUCKY` mode that does exactly this), but nothing in Cognee's documentation confirms it routes based on how a query is *phrased* the way the original version of this section assumed. Don't rely on phrasing to control graph-traversal vs vector-similarity behavior. Instead, drop to the lower-level `cognee.search()` call and pass an explicit `query_type` — this is deterministic and is the pattern shown throughout Cognee's own docs and examples:

```python
from cognee import search, SearchType

async def build_professor_context(paper_id: str, question: str, user_id: str) -> dict:
    # explicit graph traversal: pulls prerequisite chains and structural relationships
    prereq_context = await search(
        query_text=f"prerequisites required to understand: {question}",
        query_type=SearchType.GRAPH_COMPLETION,
        datasets=["paper_concepts"],
    )
    # explicit similarity search: pulls semantically relevant explanation material
    explanation_context = await search(
        query_text=question,
        query_type=SearchType.SIMILARITY,
        datasets=["paper_concepts"],
    )
    # user's actual known concepts, so the system prompt can name-check them
    known_concepts = await search(
        query_text="concepts with confidence above 0.6",
        query_type=SearchType.GRAPH_COMPLETION,
        datasets=["user_knowledge"],
    )
    return {
        "prereq_context": prereq_context,
        "explanation_context": explanation_context,
        "known_concepts": known_concepts,
    }
```

`GRAPH_COMPLETION` is Cognee's default and is built specifically for "questions that benefit from both content and structure" — it pulls a relevant subgraph and converts it to text, which is exactly what prerequisite-chain questions need. `SIMILARITY` is a pure vector lookup, useful when you want semantically-close material without caring about graph structure. There are more `SearchType` values available (`INSIGHTS`, `CHUNKS`, `COMPLETION`/`RAG_COMPLETION`, and several `GRAPH_COMPLETION_*` variants like `COT` and `CONTEXT_EXTENSION`) — worth a quick look at whichever ones are exposed in your installed version on Day 1, since the exact enum surface can shift between releases. Don't guess at names in code; import `SearchType` and check `dir(SearchType)` or your IDE's autocomplete once you're set up, and confirm against whichever values actually exist before you hardcode them into `professor.py`.

One more native mechanism worth using instead of building your own session-transcript persistence: `remember(text, session_id="chat_1")` stores ephemeral, session-scoped memory that Cognee background-syncs toward the graph on its own, and `improve(dataset=..., session_id="chat_1")` explicitly bridges that session into permanent memory at session end. That's your Section 7's `improve()`-at-session-end step, natively — lean on it rather than hand-rolling the bridging logic. You still want a small local object holding the running turn-by-turn transcript (Cognee's session memory won't hand you back a clean chat history formatted for a system prompt), but the *permanent-graph bridging* part is Cognee's job, not yours to reimplement.

### 7.3 Prompt 4 — Professor system prompt, full text

```xml
<role>
You are a patient, precise professor helping a learner understand a
research paper. You have access to exactly what this learner already
knows and does not know.
</role>
<learner_known_concepts>
{known_concepts_list}
</learner_known_concepts>
<current_gap_concepts>
{gap_list_for_this_paper}
</current_gap_concepts>
<instructions>
When explaining a concept:
1. Actively use the learner's known concepts as scaffolding — reference
   them by name when they're genuinely relevant, don't force connections
   that aren't real.
2. Never assume understanding of anything not listed in known_concepts.
   If an explanation needs a concept the learner doesn't have, either
   explain that concept briefly first or explicitly flag it as a
   prerequisite they should study.
3. Keep explanations concrete — use the paper's own notation and examples
   where possible rather than generic textbook phrasing.
4. End substantive explanations with a light comprehension check
   ("does that connect to what you know about X?") rather than assuming
   the explanation landed.
</instructions>
<conversation_history>
{recent_turns}
</conversation_history>
```

### 7.4 Turn loop and confidence signal detection

Every chat turn does double duty: generate the explanation, *and* classify whether the turn itself is a confidence signal (Prompt 5, Section 9). Don't make these two separate LLM calls if you can help it — that doubles your rate-limit spend on every single chat message. Instead, ask for both in one structured response:

```xml
<output_format>
Return a JSON object inside <output> tags with two fields:
"response": your explanation to the learner, as plain text (not JSON-escaped
  markdown, just natural prose you'd say aloud)
"confidence_signal": null, or an object {"concept": "...", "signal_type":
  "understood"|"confused"|"already_knew", "detected_from": "quote of the
  learner's message that indicated this"} if the learner's most recent
  message contains a clear confidence signal about a specific concept.
  Only populate this if the signal is unambiguous — do not guess.
</output_format>
```

This single change — combining explanation generation and signal classification into one call — roughly halves your per-turn LLM cost, which matters a great deal against a 200/day budget during a live demo where judges may ask you to interact with it multiple times.

---

## Next section

This covers Cognee's data layer, the OpenRouter/LLM pipeline, extraction and dependency-mapping prompts, gap analysis, and the professor agent's orchestration. Say the word and I'll do **Part 2**: the confidence-scoring engine's locking/race-condition handling in full, the FastAPI backend with the async job-status pattern for paper uploads (endpoint code, Pydantic models, background task structure), the caching layer implementation, and the day-by-day build checklist mapped against your original 7-day schedule — worth noting, today is July 3, which lines up with "Day 5: improve() + forget() feedback loop" on your original table, so Part 2 will flag where that puts you relative to the plan.

# PaperMind — Concept Extraction & PDF Pipeline
### Part 4: PDF processing, concept/dependency extraction, Wikipedia + Semantic Scholar enrichment, writing into Cognee without double-paying for LLM calls

Continues from Parts 1-3. Read Part 3 Section 5 (Custom Data Models) before this — the write-to-Cognee step here depends on it.

---

## 0. The LLM-cost insight, stated precisely, since it reshapes this whole pipeline

Guided-text `remember()` isn't free the way it looks. Under the hood, `remember()` runs `add + cognify + improve`, and `cognify()` calls an LLM to extract entities and relationships from whatever text you hand it — that's a second, independent LLM call on top of your own concept-extraction and dependency-mapping prompts, and it's pointed at the same OpenRouter account and the same 200/day free-tier ceiling. Ingest twenty papers' worth of guided text this way and you've quietly doubled your LLM spend for no accuracy gain — you already extracted the concepts and edges precisely with your own prompts; asking Cognee's internal LLM to re-derive the same structure from prose is redundant work paid for twice.

The fix: for `paper_concepts`, **skip `remember()` and write typed `DataPoint`/`Edge` objects directly with `add_data_points()`.** This uses only Cognee's local embedding model (fastembed, free, no rate limit) to index the fields you choose — no LLM call at all for structure, since you're handing Cognee the structure already built. `paper_concepts` is append-only and rarely needs per-item deletion (Part 1's own observation), so the standalone-`add_data_points()` dataset-association gotcha from Part 3 Section 5 doesn't bite you here — you're not trying to `forget()` individual concepts out of this dataset.

This is the single most consequential change in this document. Everything else below is built around it.

---

## 1. Revised pipeline sequence

1. PDF upload arrives as a FastAPI `UploadFile`
2. Cache check: MD5 of PDF bytes → cache hit means skip straight to step 9
3. **Track A (selective):** pdfplumber full-text extraction → section detection → Abstract+Intro+Methodology slice, capped ~3000 words — feeds the LLM extraction prompts
4. **Track B (full-text, parallel, independent):** the same `UploadFile` passed directly to `cognee.remember(dataset_name=f"paper_{paper_id}_fulltext")` — Cognee chunks and indexes the whole paper for the chatbot's RAG layer, no manual chunking code needed
5. Concept extraction LLM call (Prompt 1) on Track A's text slice
6. Dependency mapping LLM call (Prompt 2) on the concept list from step 5
7. Cycle validation on the returned edges (deterministic code, no LLM)
8. Wikipedia enrichment, concurrent across all concepts (no LLM, pure API)
9. Semantic Scholar enrichment for the paper's own references (no LLM, pure API)
10. **Write typed `Concept`/`Edge` DataPoints directly into `paper_concepts` via `add_data_points()`** — no LLM call, local embeddings only
11. Cache write: paper hash → the full concept+edge+enrichment result, so a re-upload skips everything above

Tracks A and B can run concurrently (`asyncio.gather`) since they don't depend on each other — Track B doesn't need Track A's extraction results at all, it's independently chunking the raw file.

---

## 2. PDF Pipeline — section detection, refined

Unchanged in substance from Part 1 Section 4.2, reproduced here as the canonical version since this document is meant to be self-contained for this part of the build:

```python
# pipelines/pdf_pipeline.py
import re
import pdfplumber
from io import BytesIO

SECTION_HEADERS = [
    "abstract", "introduction", "related work", "background",
    "methodology", "method", "approach", "architecture",
    "experiments", "results", "evaluation", "discussion",
    "conclusion", "references", "acknowledgments",
]

def extract_full_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)

def detect_sections(full_text: str) -> dict[str, str]:
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

def get_extraction_slice(sections: dict[str, str], max_words: int = 3000) -> str:
    """
    Returns the Abstract + Introduction + Methodology slice for the
    concept-extraction prompt. Falls back to the first max_words of the
    full text if fewer than 3 recognizable sections were found — this is
    the graceful-degradation path for oddly-formatted PDFs (two-column
    layouts, non-standard headers) so the pipeline never hard-fails here.
    """
    wanted = ["abstract", "introduction", "methodology", "method", "approach"]
    found = [sections[k] for k in wanted if k in sections and sections[k].strip()]
    if len(found) >= 2:
        combined = "\n\n".join(found)
    else:
        combined = "\n".join(sections.values())
    words = combined.split()
    return " ".join(words[:max_words])

def get_references_text(sections: dict[str, str]) -> str:
    return sections.get("references", "")
```

**On the ~10% of papers this heuristic mishandles:** the fallback in `get_extraction_slice` (fewer than 2 recognized sections → just take the first N words of everything) is deliberate and sufficient for a hackathon — don't invest more time here. If a judge's own uploaded paper trips this fallback during a live demo, the pipeline still produces *a* concept list, just a slightly noisier one; it doesn't crash. That's the right failure mode to design for.

---

## 3. Concept Extraction — Prompt 1, unchanged from Part 1, reproduced for continuity

```xml
<instructions>
You are analyzing a research paper to build a prerequisite knowledge map
for a learner. Extract every distinct technical concept a learner must
understand to comprehend this paper's core contribution.

Be granular: prefer "gradient descent with momentum" over "machine learning".
Prefer "scaled dot-product attention" over "attention".
Aim for 15-30 concepts for a typical paper.

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

Call it through the `call_llm()` + `extract_json()` pair from Part 1 Sections 3.1-3.2 (model fallback chain, markdown-fence stripping, trailing-comma repair). Nothing changes here — this prompt's output feeds directly into the next step.

```python
# pipelines/concept_pipeline.py
from prompts.concept_extraction import CONCEPT_EXTRACTION_PROMPT
from pipelines.llm_client import call_llm, extract_json
from knowledge.canonical import canonical

async def extract_concepts(text_slice: str) -> dict:
    prompt = CONCEPT_EXTRACTION_PROMPT.format(abstract_intro_methodology=text_slice)
    raw = await call_llm(prompt, system="You are a precise technical concept extractor.")
    parsed = extract_json(raw)
    # canonicalize every concept name immediately, at the earliest possible point,
    # so nothing downstream ever has to remember to do it
    for c in parsed["concepts"]:
        c["canonical_name"] = canonical(c["name"])
    return parsed
```

---

## 4. Dependency Mapping — Prompt 2, with the cycle guard as a hard gate

```xml
<instructions>
Given this list of technical concepts extracted from a research paper,
build a directed prerequisite graph. For each concept, list which OTHER
concepts from this same list it depends on.

Only use concepts from the provided list. A concept with no prerequisites
from this list should have an empty array. Avoid cycles: if A requires B
and B requires A, choose the more fundamental one as the prerequisite.
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

```python
async def map_dependencies(concepts: list[dict]) -> dict[str, list[str]]:
    names = [c["canonical_name"] for c in concepts]
    prompt = DEPENDENCY_MAPPING_PROMPT.format(json_list_of_concept_names=json.dumps(names))
    raw = await call_llm(prompt, system="You are a precise dependency-graph builder.")
    parsed = extract_json(raw)
    edges = {canonical(e["concept"]): [canonical(r) for r in e["requires"]] for e in parsed["edges"]}
    return validate_and_break_cycles(edges)

def validate_and_break_cycles(edges: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    DFS-based cycle detection. If a cycle is found, the edge that closes
    the cycle is dropped and logged — this must run before the edges ever
    reach the topological sort in Section 6 of Part 1, since a cycle there
    is a hard crash at demo time, not a soft failure.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in edges}
    dropped = []

    def dfs(node, path):
        color[node] = GRAY
        for prereq in list(edges.get(node, [])):
            if prereq not in color:
                continue  # prereq not in this concept list, nothing to check
            if color[prereq] == GRAY:
                # closing a cycle: drop this specific edge, not the whole node
                edges[node].remove(prereq)
                dropped.append((node, prereq))
                continue
            if color[prereq] == WHITE:
                dfs(prereq, path + [prereq])
        color[node] = BLACK

    for n in list(edges.keys()):
        if color[n] == WHITE:
            dfs(n, [n])

    if dropped:
        print(f"[cycle guard] dropped {len(dropped)} edge(s) to break cycles: {dropped}")
    return edges
```

Recursion depth is bounded by concept count (15-30 per paper), so plain recursive DFS is fine here — no need for an iterative version for this scale.

---

## 5. Writing to Cognee — typed DataPoints, no double LLM cost

This replaces Part 1 Section 2.3's guided-text templates for `paper_concepts` specifically, per Section 0's reasoning above.

```python
# knowledge/cognee_write.py
from cognee.infrastructure.engine import DataPoint
from cognee.infrastructure.engine.models.Edge import Edge
from cognee.tasks.storage import add_data_points
from typing import Any
from pydantic import SkipValidation

class ConceptNode(DataPoint):
    name: str                      # canonical_name
    display_name: str
    definition: str = ""
    category: str = "prerequisite"  # "prerequisite" | "introduced"
    paper_id: str = ""
    resource_urls: SkipValidation[Any] = None   # list[str], SkipValidation for the list type
    requires: SkipValidation[Any] = None         # single ConceptNode or list[ConceptNode]
    metadata: dict = {"index_fields": ["name", "display_name", "definition"]}

async def write_paper_to_cognee(concepts: list[dict], edges: dict[str, list[str]],
                                  enriched: dict[str, dict], paper_id: str) -> None:
    nodes: dict[str, ConceptNode] = {}
    for c in concepts:
        cname = c["canonical_name"]
        wiki_data = enriched.get(cname, {})
        nodes[cname] = ConceptNode(
            name=cname,
            display_name=c["name"],
            definition=wiki_data.get("definition", c.get("brief_context", "")),
            category=c["category"],
            paper_id=paper_id,
            resource_urls=wiki_data.get("resource_urls", []),
        )

    # wire up requires edges now that every node exists
    for concept_name, prereq_names in edges.items():
        if concept_name not in nodes:
            continue
        prereq_nodes = [nodes[p] for p in prereq_names if p in nodes]
        if not prereq_nodes:
            continue
        edge = Edge(relationship_type="requires", weight=1.0)
        nodes[concept_name].requires = (edge, prereq_nodes) if len(prereq_nodes) > 1 else (edge, prereq_nodes[0])

    await add_data_points(list(nodes.values()))
```

Two things to verify by hand on Day 1-2, same spirit as Part 3's smoke test — this is new surface area beyond what that test covered:

- **Does a list-of-Edges-with-multiple-targets actually work the way it's written above** (`(edge, [prereq1, prereq2])`), or does Cognee's `Edge` wiring expect one edge object per target pair rather than one shared edge object fanning out to a list? The Custom Data Models doc's own example (`bob.knows = (Edge(...), charlie)`) only shows the single-target form directly, and mentions the list form separately without showing them combined with a custom weight/type in the same line. Test with a 3-concept, 2-edge toy example before running this against a real 25-concept paper.
- **Does `SIMILARITY` and `INSIGHTS` search against `paper_concepts` actually surface these directly-added nodes correctly**, given they never passed through `cognify()`'s LLM extraction — the embeddings come from `index_fields`, but confirm the graph traversal side (which nodes/edges appear in `INSIGHTS` results) works the same for directly-added DataPoints as it does for cognify-derived ones. This directly determines whether Part 3's `INSIGHTS`-based dependency queries in `professor.py` will actually return your `requires` edges. If it doesn't work as expected, the fallback is: use guided-text `remember()` for edges specifically (accepting the extra LLM call) while keeping the LLM-free `add_data_points()` path for concept nodes and definitions, which is where most of the token cost would otherwise go.

---

## 6. Wikipedia Enrichment — concurrent, unchanged in substance from Part 1

```python
# pipelines/wiki_pipeline.py
import asyncio
import wikipediaapi

wiki = wikipediaapi.Wikipedia(user_agent="PaperMind/1.0", language="en")

async def fetch_wikipedia(concept_name: str) -> dict:
    from cache.cache_manager import wiki_cache
    from knowledge.canonical import canonical

    key = canonical(concept_name)
    cached = wiki_cache.get(key)
    if cached:
        return cached

    def _sync_fetch():
        page = wiki.page(concept_name)
        if not page.exists():
            return {"definition": None, "resource_urls": []}
        summary = page.summary.split(". ")
        definition = ". ".join(summary[:2]) + "."
        return {
            "definition": definition,
            "resource_urls": list(page.links.keys())[:5],  # candidate related concepts, not URLs strictly,
                                                              # but useful signal — see note below
        }

    result = await asyncio.to_thread(_sync_fetch)  # wikipedia-api is sync; don't block the event loop
    wiki_cache.set(key, result)
    return result

async def enrich_all(concept_names: list[str]) -> dict[str, dict]:
    results = await asyncio.gather(
        *[fetch_wikipedia(name) for name in concept_names],
        return_exceptions=True,
    )
    return {
        name: (r if not isinstance(r, Exception) else {"definition": None, "resource_urls": []})
        for name, r in zip(concept_names, results)
    }
```

One correction to Part 1's version worth flagging: `wikipedia-api` (the `wikipediaapi` package) is a **synchronous** library — there's no native async client. Running it directly inside an `async def` blocks the event loop for the duration of each HTTP call, which quietly defeats the whole point of `asyncio.gather()`-based concurrency from Part 1 Section 5. Wrapping the sync call in `asyncio.to_thread()` (shown above) is the fix — it runs each Wikipedia lookup in a thread pool so they genuinely overlap in wall-clock time instead of queuing one after another. This is a real bug I'd have shipped if I hadn't caught it now; worth testing with a 10-concept batch on Day 1 to confirm actual wall-clock concurrency (time it — should be close to the slowest single lookup, not the sum of all of them).

`page.references` (external citation URLs, mentioned in your original overview) isn't reliably exposed as clean URLs by the `wikipediaapi` package the way `page.links` (related-page titles) is — verify this against the actual package's API on Day 1 before assuming both are available in the form your original plan described. If `page.references` doesn't give you clean URLs directly, `page.fullurl` (the Wikipedia article's own URL) is a reliable fallback resource link even if it's a single link rather than several citations.

---

## 7. Semantic Scholar Enrichment — unchanged from Part 1, reproduced briefly

```python
# pipelines/scholar_pipeline.py
import httpx

async def get_paper_references(paper_title: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": paper_title, "fields": "title,abstract,references"},
        )
        if resp.status_code != 200 or not resp.json().get("data"):
            return []
        paper = resp.json()["data"][0]
        return paper.get("references", [])[:20]  # cap it, you're using titles as signals, not fetching all
```

No LLM cost, no rate-limit interaction with OpenRouter — safe to call on every upload without caching concern, though caching it anyway (keyed by paper title) costs nothing and avoids redundant network calls on repeat testing.

---

## 8. Full orchestration, updated to match the corrected write path

This replaces Part 2 Section 8.2's `process_paper_job` body — same staged structure, same `set_stage()` progress reporting, updated to reflect Tracks A/B running concurrently and the `add_data_points()` write path:

```python
async def process_paper_job(job_id: str, pdf_bytes: bytes, filename: str, upload_file):
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
        full_text = pdf_pipeline.extract_full_text(pdf_bytes)
        sections = pdf_pipeline.detect_sections(full_text)
        text_slice = pdf_pipeline.get_extraction_slice(sections)

        paper_id = str(uuid.uuid4())

        # Track A (concept extraction) and Track B (full-text chatbot ingestion)
        # run concurrently — they don't depend on each other
        set_stage("extracting_concepts_and_indexing_fulltext")
        concepts_task = concept_pipeline.extract_concepts(text_slice)
        fulltext_task = cognee.remember(upload_file, dataset_name=f"paper_{paper_id}_fulltext")
        parsed_concepts, _ = await asyncio.gather(concepts_task, fulltext_task)
        concepts = parsed_concepts["concepts"]

        set_stage("mapping_dependencies")
        edges = await concept_pipeline.map_dependencies(concepts)

        set_stage("enriching_wikipedia")
        enriched = await wiki_pipeline.enrich_all([c["canonical_name"] for c in concepts])

        set_stage("enriching_scholar")
        scholar_refs = await scholar_pipeline.get_paper_references(parsed_concepts["paper_title"])

        set_stage("writing_to_graph")
        await cognee_write.write_paper_to_cognee(concepts, edges, enriched, paper_id)

        cache_manager.save_paper_result(pdf_hash, {
            "paper_id": paper_id,
            "concepts": concepts,
            "edges": edges,
        })
        jobs[job_id] = {"status": "done", "stage": "complete", "paper_id": paper_id, "error": None}

    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": jobs[job_id]["stage"], "paper_id": None, "error": str(e)}
```

Note the cache now stores `concepts` and `edges` directly, not just the `paper_id` — this matters because a cache hit should be able to serve `/roadmap/{paper_id}` without re-querying Cognee at all if you want the fastest possible repeat-demo path; a cache hit that only remembers the `paper_id` still requires a live Cognee read on every subsequent request. Worth deciding by Day 3 whether your `/roadmap` endpoint reads from this local cache or from Cognee directly — reading from Cognee is more "real" for judges inspecting your architecture, reading from cache is faster and more demo-safe. A reasonable middle ground: read from Cognee, but keep the cache as a fallback if a Cognee call fails or times out mid-demo.

---

## 9. What to actually test, in order, Day 1-2

1. Section detection + extraction slice on 2-3 real papers you'll likely use in the demo (including the one from your demo script). Confirm the fallback path doesn't silently trigger on papers that should hit the primary heuristic.
2. Prompt 1 + Prompt 2 in isolation, against the fallback model chain, checking `extract_json()`'s repair logic actually fires correctly on at least one deliberately-malformed test string.
3. The cycle guard, with a deliberately cyclic toy `edges` dict, confirming it drops exactly the closing edge and doesn't over-prune.
4. The `ConceptNode`/`Edge` write path from Section 5, on a 3-node toy example first, then a real paper's full 15-30 nodes — this is where the two open Cognee-behavior questions from Section 5 get answered.
5. `asyncio.to_thread`-wrapped Wikipedia enrichment, timed, on a 10-concept batch, confirming real concurrency.

If you hit a wall on the `add_data_points()` edge-wiring question in Section 5 and don't want to burn Day 1-2 debugging it, the documented fallback (guided-text `remember()` for edges only) is a legitimate fallback — just budget the extra LLM calls it costs against your daily total if you take that path.

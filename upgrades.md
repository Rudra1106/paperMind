1. What has to change, layer by layer
Backend

- Free-tier LLM chain is your biggest liability. deepseek-chat:free → llama-3.1-8b:free → qwen-2.5-72b:free on OpenRouter will rate-limit under real traffic and the 8B fallback will silently degrade extraction quality. For real users you need a paid primary model (GPT-4.1-mini / Claude Haiku / Gemini Flash tier) with the free chain only as an emergency fallback, plus per-user rate limiting instead of a global 200/day budget. 
we will shift to paid models later , for now lets stick to free models.
- In-memory job store → Redis or Postgres-backed queue (Celery/RQ/Arq). A server restart currently loses every in-flight upload — unacceptable once someone's mid-paper.
i will added redis api key and supabase api key in env , lets use them. 
- Auth + multi-tenancy. Right now everything is single-user. You need user accounts, and Cognee datasets namespaced per user (user_{uid}_knowledge__{concept}), not just per concept. This is a real architectural change, not a config flag.
Move the cache from local JSON to a real DB (Postgres for metadata, S3/R2 for PDFs) so it survives deploys and scales across instances.
Observability: structured logging, LLM cost tracking per user, error tracking (Sentry). You'll need to know which papers break your section-detection heuristic in the wild.
- For PapersMind specifically: Supabase, with an option to add R2 later for one specific use case.
Why Supabase:
our PDFs are private, per-user documents — auth needs to gate access. Supabase Storage is the right call when the data is small, tied to auth, and you don't want to wire a second service, since Storage policies integrate with Row Level Security so authorization can be handled in one place. R2 has no equivalent — you'd have to handle auth yourself in a Worker. AdamarantPuter
You already need Postgres for user accounts, job status, and confidence scores. Supabase gives you that database plus storage plus auth in one platform, so Storage layers on top of the same database with automatic CDN delivery rather than wiring a second vendor. BuildMVPFast
PDFs are read-doesn't-dominate: each paper gets uploaded once and read by roughly one user, not downloaded thousands of times publicly. That's exactly the profile where Supabase Storage works well and R2's zero-egress advantage doesn't really pay off. Adamarant

When you'd want R2 too: if you build the public no-login demo I mentioned (pre-loaded famous papers anyone can try), those specific PDFs will get fetched repeatedly by anonymous visitors with no auth needed — that's public, high-download, no-RLS-required content, which is exactly the split real SaaS teams use in 2026: Supabase Storage for anything tied to a logged-in user, and R2 behind a CDN for everything served broadly to the public. Adamarant
One real gotcha to plan around: Supabase's free tier is tight — 1 GB storage and 5 GB egress, and free projects pause after a week of inactivity, and someone building a similar AI product hit the Supabase storage-exceeded wall and found Supabase costs grow fast with scale — the same workload cost roughly $500/month on Supabase vs about $2/month on R2 at 1000 projects/month. That's specifically an egress/bandwidth story though, not a per-PDF-storage story — for your use case (moderate number of PDFs, mostly read once by their owner), that curve won't hit you nearly as hard as it hit an image-generation app. Puter + 2
- start on Supabase alone (simpler, one less service, auth already solved). Migrate only the public-demo papers to R2 once/if that free-demo traffic actually shows up — that's a small, well-isolated change since R2 is straightforward to add for large-file storage with zero egress while keeping Supabase for everything else
supabase free tier : Unlimited API requests
50,000 monthly active users
500 MB database size
Shared CPU • 500 MB RAM
5 GB egress
5 GB cached egress
1 GB file storage
Community support

# Frontend

Vanilla CSS + Canvas force layout is fine for a hackathon; for real users invest in a proper design system (or Tailwind + shadcn) — the graph visualization especially needs polish (zoom, search-within-graph, node clustering for 100+ concepts) since it's your visual hook.
Add real onboarding: a "what do you already know" quick calibration instead of starting every paper at zero confidence — cold-start is the biggest UX killer for a personalization product.
Progressive disclosure: don't dump 24 concepts on someone at once. Show the top 3–5 blocking concepts first.
Mobile-responsive at minimum — a lot of your discovery traffic (Twitter/HN/Reddit) will be on phones.

AI agents / models

Split extraction and chat into properly evaluated prompt pipelines with a golden test set (20–30 known papers with human-labeled concept lists) so you can measure precision/recall on concept extraction before and after prompt changes — right now you have no way to know if a prompt tweak made things better or worse.
Add a verification pass: after extraction, a second cheap LLM call (or embedding similarity check) that flags hallucinated concepts not actually in the text.
The "one LLM call does explanation + signal classification" trick is smart for cost but caps quality — as you scale, separate them behind a feature flag so you can A/B whether joint vs separate calls actually hurts chat quality.

Datasets / Knowledge graph

Cognee Cloud free tier and 50–150 datasets/user is explicitly called out in your own README as not scaling. This is the one that will bite hardest — before "real users," pressure-test with 20 concurrent users each uploading 3 papers and see where it breaks.
Consider a canonical concept ontology (a maintained taxonomy of ML/AI concepts you seed ahead of time) rather than purely LLM-extracted per paper — this lets cross-paper concept matching be exact-match instead of fuzzy alias resolution, and it's a defensible moat competitors can't trivially copy.

Data processing

pdfplumber's "first 3000 words" fallback for 2-column/non-standard papers is a real quality cliff. Add a layout-aware extractor (e.g. unstructured, or a vision-model pass on rendered pages) as a second tier before falling back to naive slicing.
Add support for arXiv URLs directly (fetch + extract), not just PDF upload — friction reduction matters a lot for growth.

Presentation (for going viral / getting attention)

A public, no-login "try it on this paper" demo with 3–5 pre-loaded famous papers (Attention Is All You Need, ResNet, etc.) so people can experience the "aha" in 10 seconds without signing up — this is what actually drives Twitter/HN shares.
A shareable knowledge graph view (public read-only link) so people post screenshots — visual, novel things are what spread.

2. Building for real users / getting visibility
Practical sequence, roughly in order:

Ship the free public demo first (above) — this is your distribution wedge, not sign-ups.
Post launch on Hacker News (Show HN), r/MachineLearning, and Twitter/X AI community with a short video/GIF of the roadmap re-ordering live — that's your most visually compelling moment.
Target a real underserved audience: PhD students and self-taught ML engineers reading papers outside their subfield. Niche-specific distribution (ML Twitter, paper-reading Discord servers, r/MLQuestions) will convert far better than broad audiences.
Instrument everything from day one — which papers get uploaded, where users drop off, which chat questions get asked — you can't iterate on what you don't measure.
Solve the cold-start problem explicitly — right now confidence starts at 0 for everyone; a quick "rate your familiarity with these 5 core ML concepts" onboarding massively improves first-session value.

3. Turning it into a genuinely great full learning agent
The prototype proves the graph works. The next tier is turning it from "explains a paper" into "helps you actually learn":

Spaced repetition layer on top of confidence scores — Cognee already tracks confidence decay potential; add scheduled review prompts ("you marked attention as understood 3 weeks ago — quick check?").
Multi-paper synthesis: once someone's uploaded 5+ papers, generate a personal "concept mastery map" across their whole reading history, not per-paper — this is where the graph architecture really pays off vs any RAG competitor.
Active recall, not just passive chat: the professor agent should sometimes quiz the user on a concept rather than only answering questions — this is proven to improve retention far more than re-reading explanations.
Multi-modal explanation: let the professor generate a quick diagram/equation walkthrough inline, not just text, for concepts like attention mechanisms where a visual genuinely helps.
Community graph layer (longer-term, careful with privacy): aggregate anonymized "which concepts do most people get stuck on in this paper" to pre-flag common confusion points for new readers — network effects that make the product better as more people use it.

# 1. Multi-tenant Cognee dataset scheme
The core decision first: don't put confidence scores in Cognee at all.
Your README already flags the real problem — add_data_points() creates nodes with no dataset association, so forget() can't target them, forcing one Cognee dataset per concept per user. At 50–150 datasets/user that's your own doc calling out it won't survive real traffic. The fix isn't a cleverer Cognee dataset scheme — it's recognizing that confidence scores are simple mutable scalars, and Cognee is a graph/semantic memory engine, not a scalar store. Split responsibilities:
DataWhereWhyPaper concepts, prerequisite edges, definitions, full-text for chat RAGCogneeStructural/semantic — what it's built forPer-user confidence scoresPostgres (Supabase, see #5)One row per (user_id, concept_id), trivially updatable, trivially queryable, zero dataset explosion
This alone kills your biggest scaling liability and simplifies the confidence engine to a normal SQL UPDATE.
Now the Cognee side, using the native permission system (not string prefixes):
ENABLE_BACKEND_ACCESS_CONTROL=true   # real EBAC, not manual namespacing

Map each Supabase Auth user 1:1 to a Cognee User (create_user, keyed by the Supabase user.id as email/external id) at signup — one extra API call in your auth webhook.
One shared dataset per paper, not per user: paper_{paper_id}_concepts, owned by a system service user (call it papermind_service), populated once via add_data_points() the first time any user uploads that PDF (you already MD5-cache PDFs — reuse the hash as the paper identity). Grant Read to a papermind_readers Role, and add every new user to that role at signup. Result: 1000 users uploading "Attention Is All You Need" share one graph instead of 1000 duplicate extraction runs — this is a direct cost win on top of being architecturally cleaner.
One dataset per user for session/chat memory: user_{user_id}_session, owned by that user, used for the existing remember(session_id=...) → improve() bridging. This is genuinely per-user mutable content (chat turns), so it belongs in Cognee.
If you ever add classrooms/teams: model as a Cognee Tenant, with the professor's uploaded paper set shared Read-only to all students in that tenant — this maps directly onto Cognee's existing Tenant→Role→User permission inheritance, no custom code needed.

Filesystem/storage implication: with EBAC on, Cognee auto-isolates per-user Kùzu/LanceDB files (.cognee_system/databases/<user_uuid>/...) — fine for dev, but for production point the relational store at Postgres (not SQLite) since that's the only backend the docs list as production-ready for the permissions tables. Good news: this is the same Postgres instance you'll use for Supabase in #5 — one database, two roles.
Net effect on your architecture:

Cognee datasets per user drops from "50–150" to 1 (session memory) — solves your own documented scaling limit.
Paper graphs become shared, cutting LLM extraction cost roughly by (avg uploads per unique paper) — meaningful once you get any organic traffic on popular papers.
Confidence updates go from forget()+remember() with a per-concept lock to a normal Postgres row update — faster, and the lock becomes unnecessary since Postgres handles concurrent writes natively (still wrap in a transaction if two triggers can fire in the same request).

# 3. Redesigning your prompts with Claude's official techniques
Two things from the current docs matter most for your specific pipeline: XML tags are not cosmetic for Claude — it's specifically fine-tuned to attend to them, so structure (not just wording) drives reliability — and for JSON extraction tasks, grounding-before-extracting (ask the model to quote/point to the source text before it commits to structured output) measurably cuts hallucination on long documents.
Here's your concept extraction prompt (Prompt 1) rewritten with the full technique stack — role, clear+direct instructions, XML structuring, grounding, multishot example, and chain-of-thought before the structured answer:
xmlYou are a research paper analyst who identifies the exact prerequisite
knowledge a reader needs before they can understand a given paper section.
You are precise and conservative: you only extract concepts that are
genuinely present or assumed, never concepts that merely sound related.

<instructions>
1. Read the <paper_excerpt> below.
2. In <thinking> tags, list the 5-10 most technical noun phrases in the
   excerpt, and for each, note whether the paper explains it (a "new"
   concept the paper teaches) or assumes the reader already knows it
   (a "prerequisite" concept).
3. In <answer> tags, output ONLY the JSON object described in <output_format>.
   No text before or after the JSON.
</instructions>

<output_format>
{
  "concepts": [
    {
      "name": "string, lowercase, canonical form",
      "aliases": ["string", ...],
      "category": "prerequisite" | "new",
      "evidence_quote": "string, <20 words, copied verbatim from the excerpt"
    }
  ]
}
</output_format>

<examples>
<example>
<paper_excerpt>
We compute attention weights via a softmax over scaled dot products of
queries and keys, following the standard scaled dot-product attention
mechanism used in prior transformer architectures.
</paper_excerpt>
<thinking>
"softmax" - assumed known, standard ML op -> prerequisite
"scaled dot-product attention" - paper explicitly names it as the
mechanism it uses, doesn't re-derive it -> prerequisite
"transformer architectures" - referenced as prior work, not explained -> prerequisite
</thinking>
<answer>
{"concepts": [
  {"name": "softmax", "aliases": ["softmax function"], "category": "prerequisite", "evidence_quote": "softmax over scaled dot products"},
  {"name": "scaled_dot_product_attention", "aliases": ["scaled dot-product attention"], "category": "prerequisite", "evidence_quote": "standard scaled dot-product attention mechanism"}
]}
</answer>
</example>
</examples>

<paper_excerpt>
{{PAPER_TEXT}}
</paper_excerpt>
What changed vs. a typical hackathon prompt, and why each change earns its place:

evidence_quote field forces the model to point at real text before naming a concept — this is the single highest-leverage change for killing hallucinated concepts, and it's free: you already have the source text to validate the quote against in code (reject any concept whose quote isn't a substring match).
<thinking> before <answer> — with thinking mode off (which you need on free-tier models for cost/latency), this manual CoT pattern is the documented fallback, and separating it from the answer means you can strip it before parsing JSON instead of fighting it in extract_json().
One worked example inside <examples>, not a plain description — docs are explicit that 3-5 examples are ideal for consistency; even one well-chosen example dramatically reduces category confusion (prerequisite vs. new) which is exactly where your free-tier models will drift.
Role sentence up top ("precise and conservative") — a single sentence in the system position measurably changes behavior; yours currently has none.

Apply the same pattern to Prompt 2 (dependency mapping): add a worked example showing one clean prerequisite edge and one rejected false edge (e.g. "multi-head attention requires positional encoding" — plausible-sounding but wrong), since showing what not to extract is often more useful than showing what to extract, and your DFS cycle-guard exists precisely because free models invent spurious edges.
Professor chat system prompt — same principles, different shape:
xmlYou are a professor who adapts every explanation to exactly what this
student already knows. Never re-explain a concept marked "known" below;
build new explanations on top of it instead.

<student_known_concepts>{{KNOWN_LIST}}</student_known_concepts>
<student_gaps>{{GAP_LIST}}</student_gaps>
<retrieved_context>{{COGNEE_SEARCH_RESULTS}}</retrieved_context>

<instructions>
Answer the student's question using <retrieved_context>. Then classify
the turn. Output both in the JSON format in <output_format> — no other text.
</instructions>
This is close to what you likely have — the main gap to close is wrapping the three Cognee search results (INSIGHTS/GRAPH_COMPLETION/SIMILARITY) in their own labeled tags rather than concatenating them, so the model can weight structural vs. semantic evidence differently, which the docs' "structure document content with metadata" guidance covers directly.
One structural note for production: your free-tier fallback chain (deepseek → llama-3.1-8b → qwen-2.5-72b) will follow this XML structure with meaningfully less reliability than Claude does — Claude was specifically trained to attend to it, smaller open models are hit-or-miss. Worth A/B testing Claude Haiku 4.5 as your primary extraction model (cheap, fast, and this prompt style is exactly its sweet spot) with the free chain demoted to true emergency fallback only — you'll likely see fewer JSON-repair failures and fewer cycle-guard triggers, which compounds into a smoother demo experience.


# Landing page — design plan + Vercel deployment
Design direction (grounded in the actual product, not generic AI-startup styling)
PaperMind's real subject is the space between a paper and a reader — annotation, marginalia, the moment a concept clicks. That's richer material than "AI startup," so lean into it:

Palette: paper-and-ink, not cream-and-terracotta. Background #FAF7F0 (warm paper), text #20242B (near-ink graphite), graph edges/links in a muted annotation-teal #3E7C8C, and a single warm highlighter-amber #F0B93E reserved only for "understood" states and the primary CTA — so the accent carries meaning (mastery), not just decoration.
Type: a serif display built for long-form reading (Source Serif 4 or Newsreader) for headlines — it should feel like it belongs on a paper, not a SaaS page — paired with a technical mono/sans (IBM Plex Sans + JetBrains Mono for concept-node labels) for UI chrome. The mono face doing double duty as "this is structured data" is the visual tell that separates you from a RAG chatbot skin.
Signature element: the hero isn't a headline over a stock gradient — it's a live, gently animated mini concept-graph (5–8 real nodes from an actual cached paper, e.g. "Attention Is All You Need") slowly settling into its force layout beside the headline. It's real data, it's the actual product, and it's the one thing a competitor's RAG-chatbot landing page structurally cannot show.
Structure that means something: skip generic 01 / 02 / 03 numbered steps. Use the product's own vocabulary — literal requires → edge labels — as the section dividers when you walk through the prerequisite-chain example. Structure should mirror what the graph actually does.

Section flow

Hero — live mini graph (right) + headline in the serif ("See what a paper assumes you already know") + one-line subhead + two CTAs: "Try it instantly" (loads a pre-cached famous paper, zero signup, zero LLM cost) and "Upload your own paper."
The gap, made explicit — one or two sentences, not a marketing wall. Show a real "chunk retrieval" answer next to a real "PaperMind" answer for the same question, side by side — let the contrast do the persuading.
Try a real paper — 3–4 tappable cards (Attention Is All You Need, ResNet, GPT-3, one recent arXiv paper) that load instantly because you've pre-run the pipeline and cached the result. This is your Show HN/Twitter moment — it must never hit a cold pipeline or rate limit during a launch spike.
requires → — one real prerequisite chain from an actual paper, shown as a short animated build-up (Query/Key/Value → Scaled Dot-Product Attention → Multi-Head Attention), proving the graph is real structure, not vibes.
Professor chat preview — a short, real (not fabricated) exchange, auto-playing on scroll.
Footer — GitHub/open-source link, hackathon badge, and a plain-text CTA to upload.

Copy throughout: active voice, plain verbs, no "revolutionize/unlock/leverage." Say what the button does, not what it promises.
Vercel deployment specifics (monorepo, frontend/ subfolder)

In Vercel project settings, set Root Directory to frontend — Framework Preset auto-detects Vite. Build command npm run build, output dist (defaults, no change needed).
Your backend (FastAPI + background jobs + Cognee client) cannot live on Vercel — its serverless function model doesn't support long-running background tasks or persistent job queues. Keep the backend on Render/Fly.io/Railway; Vercel hosts the static frontend only.
Use a vercel.json at the frontend root to same-origin-proxy API calls to your real backend (cleaner for a public demo URL, and sidesteps CORS entirely):

json{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://papermind-api.onrender.com/api/:path*" },
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
The second rule is required regardless — without it, refreshing on a React Router route (e.g. /roadmap/:paperId) 404s on Vercel's static host.

Environment variables: only variables prefixed VITE_ are exposed to the client bundle — set VITE_API_BASE_URL (if you skip the rewrite approach) separately per Production/Preview/Development environment in the Vercel dashboard, since your staging backend URL will differ from prod.
Preview deployments are free and automatic on every PR — genuinely useful here: point preview builds at a staging backend so you can test a prompt or roadmap-logic change against real Cognee data before it touches production users.
Turn on Vercel Analytics + Speed Insights (free tier) at launch — you'll want upload funnel and drop-off numbers from day one, and it's a checkbox, not an integration.
Before any public launch post: manually pre-run the pipeline for your 3–4 demo papers so they're cache-hits, and load-test the backend for a small concurrent burst — a Show HN spike hitting a cold job queue is the single most common way these launches fail publicly.

- strong agentic flow and orchestration.
- integration with supabase free tier: Unlimited API requests 50,000 monthly active users 500 MB database size Shared CPU • 500 MB RAM 5 GB egress 5 GB cached egress 1 GB file storage Community support
docs database : https://supabase.com/docs/guides/database/overview
docs auth : https://supabase.com/docs/guides/auth
docs storage : https://supabase.com/docs/guides/storage
- ubuilding strong backend and ai agent system for procuction
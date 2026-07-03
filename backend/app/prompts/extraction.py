"""
app/prompts/extraction.py

LLM prompt templates for concept extraction and dependency mapping.

Design decisions (from plan Part 1, Section 4.3 and 4.4):
  - Consistent XML-style tags force the model to understand what it's
    generating, reducing preamble text before the JSON.
  - The <output> tag wrapping is explicitly stripped by extract_json().
  - Temperature 0.2 — we want the same paper to produce the same concept
    list on re-runs so the cache stays meaningful.
  - "category: prerequisite | introduced" is the key field that lets the
    roadmap distinguish "you need to know this" from "this paper teaches this."
"""

CONCEPT_EXTRACTION_PROMPT = """\
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

Think step by step:
  1. Identify the paper's core contribution in one sentence.
  2. Work backward: what must a reader already know to follow that contribution?
  3. What does the paper itself introduce or teach as new?
</instructions>
<paper_content>
{abstract_intro_methodology}
</paper_content>
<output_format>
Return ONLY a JSON object inside <output> tags, no text before or after:
<output>
{{
  "paper_title": "...",
  "core_contribution": "one sentence describing what is novel here",
  "concepts": [
    {{
      "name": "scaled dot-product attention",
      "aliases": ["SDPA"],
      "category": "prerequisite",
      "brief_context": "how this concept is used in the paper, one sentence"
    }}
  ]
}}
</output>
</output_format>"""


DEPENDENCY_MAPPING_PROMPT = """\
<instructions>
Given this list of technical concepts extracted from a research paper,
build a directed prerequisite graph. For each concept, list which OTHER
concepts from this same list it directly depends on — i.e., which ones must
be understood first.

Rules:
  - Only use concept names from the provided list. Do not invent new ones.
  - A concept with no prerequisites from this list should have an empty array.
  - Avoid cycles: if you think A requires B and B requires A, choose the
    more fundamental one as the prerequisite and leave the other direction out.
  - Prefer fewer, stronger dependencies over many weak ones.
</instructions>
<concept_list>
{json_list_of_concept_names}
</concept_list>
<output_format>
Return ONLY JSON inside <output> tags:
<output>
{{
  "edges": [
    {{"concept": "multi-head attention", "requires": ["scaled dot-product attention", "linear projections"]}}
  ]
}}
</output>
</output_format>"""

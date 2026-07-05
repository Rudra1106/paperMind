"""
app/prompts/extraction.py

LLM prompt templates for concept extraction and dependency mapping.
Upgraded in Phase 3 with Claude's official techniques:
  - Role sentence
  - <thinking> CoT before <answer>
  - Evidence grounding (evidence_quote)
  - Worked examples
"""

CONCEPT_EXTRACTION_PROMPT = """\
You are a precise and highly educational research paper analyst. You identify the
exact prerequisite knowledge a reader needs before they can understand a given
paper section, and you break down the novel mechanisms introduced by the paper.
You also extract structural concepts such as limitations of prior work, 
mathematical formulations, and payoffs/results.

<instructions>
1. Read the <paper_excerpt> below.
2. In <thinking> tags, identify the core concepts. This includes fundamental prerequisites, limitations of prior work, novel mechanisms, and significant payoffs.
3. For each concept, write a highly detailed, beginner-friendly definition that explains it from first principles in the context of the paper. Avoid academic jargon where possible.
4. In <answer> tags, output ONLY the JSON object described in <output_format>.
   No text before or after the JSON.
</instructions>

<output_format>
{{
  "paper_title": "string, infer from text if possible",
  "core_contribution": "one sentence describing what is novel here",
  "concepts": [
    {{
      "name": "string, lowercase, canonical form",
      "aliases": ["string", ...],
      "category": "prerequisite" | "new" | "paper_specific_term",
      "definition": "string, highly detailed and beginner-friendly explanation",
      "evidence_quote": "string, <20 words, copied verbatim from the excerpt"
    }}
  ]
}}
</output_format>

<examples>
<example>
<paper_excerpt>
We compute attention weights via a softmax over scaled dot products of
queries and keys, following the standard scaled dot-product attention
mechanism used in prior transformer architectures. To improve efficiency, we introduce the Self-Optimizable Action Generation (SOAG) module.
</paper_excerpt>
<thinking>
"softmax" - assumed known, standard ML op -> prerequisite. Needs a beginner definition.
"scaled dot-product attention" - paper explicitly names it as the
mechanism it uses, doesn't re-derive it -> prerequisite.
"transformer architectures" - referenced as prior work, not explained -> prerequisite.
"Self-Optimizable Action Generation" - an acronym/module coined by the authors in this paper -> paper_specific_term.
</thinking>
<answer>
{{
  "paper_title": "Unknown",
  "core_contribution": "Computes attention weights using standard scaled dot-product attention and introduces the SOAG module.",
  "concepts": [
    {{"name": "softmax", "aliases": ["softmax function"], "category": "prerequisite", "definition": "A mathematical function that turns a vector of numbers into a probability distribution, making sure all values add up to 1.0.", "evidence_quote": "softmax over scaled dot products"}},
    {{"name": "scaled_dot_product_attention", "aliases": ["scaled dot-product attention"], "category": "prerequisite", "definition": "An attention mechanism that computes weights by taking the dot product of a query and key, and scaling it down to prevent vanishing gradients.", "evidence_quote": "standard scaled dot-product attention mechanism"}},
    {{"name": "transformer", "aliases": ["transformer architectures"], "category": "prerequisite", "definition": "A popular neural network architecture that relies entirely on attention mechanisms to draw global dependencies between input and output.", "evidence_quote": "prior transformer architectures"}},
    {{"name": "self_optimizable_action_generation", "aliases": ["SOAG module"], "category": "paper_specific_term", "definition": "A novel module introduced in this paper designed to improve the efficiency of action generation.", "evidence_quote": "introduce the Self-Optimizable Action Generation (SOAG) module"}}
  ]
}}
</answer>
</example>
</examples>

<paper_excerpt>
{abstract_intro_methodology}
</paper_excerpt>
"""


DEPENDENCY_MAPPING_PROMPT = """\
You are an expert at mapping the topological dependencies of machine learning
concepts. You precisely identify which concepts must be understood BEFORE
another concept can be grasped.

<instructions>
1. Read the <concept_list> below, which contains concepts extracted from a paper.
2. In <thinking> tags, for each concept, identify which OTHER concepts in the
   list are strict prerequisites. Avoid cycles (e.g., A requires B and B requires A).
3. In <answer> tags, output ONLY the JSON object described in <output_format>.
   No text before or after the JSON.
</instructions>

<output_format>
{{
  "edges": [
    {{"concept": "multi_head_attention", "requires": ["scaled_dot_product_attention", "linear_projections"]}}
  ]
}}
</output_format>

<examples>
<example>
<concept_list>
["multi_head_attention", "positional_encoding", "scaled_dot_product_attention", "linear_projections"]
</concept_list>
<thinking>
"multi_head_attention": physically built using scaled_dot_product_attention and linear_projections. It requires them.
"positional_encoding": added to inputs before attention, but attention itself doesn't depend on it. Reject this edge.
"scaled_dot_product_attention": fundamental op, no prerequisites in this list.
"linear_projections": fundamental op, no prerequisites in this list.
</thinking>
<answer>
{{
  "edges": [
    {{"concept": "multi_head_attention", "requires": ["scaled_dot_product_attention", "linear_projections"]}}
  ]
}}
</answer>
</example>
</examples>

<concept_list>
{json_list_of_concept_names}
</concept_list>
"""

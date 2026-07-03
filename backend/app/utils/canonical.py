"""
app/utils/canonical.py

The single normalization function that every concept name MUST pass through
before it touches Cognee, the alias map, or the cache.

Keeping this in one place prevents the graph fragmentation that happens when
"Multi-Head Attention", "multi head attention", and "multi-head-attention"
all become separate nodes. Called for in Part 1 Section 2.2 of the plan.
"""

import re


def canonical(name: str) -> str:
    """
    Normalise a concept name to a stable graph key.

    Rules:
      1. Lowercase
      2. Strip leading/trailing whitespace
      3. Remove non-word characters except spaces and hyphens
      4. Replace spaces and hyphens with underscores

    Examples:
      "Multi-Head Attention"         → "multi_head_attention"
      "multi head attention"         → "multi_head_attention"
      "Scaled Dot-Product Attention" → "scaled_dot_product_attention"
      "MHA (multi-head attn.)"       → "mha_multihead_attn"
    """
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)   # strip punctuation (keep letters, digits, spaces, hyphens)
    s = re.sub(r"[\s-]+", "_", s)    # collapse spaces/hyphens into a single underscore
    return s.strip("_")              # remove any leading/trailing underscores


def user_knowledge_dataset_name(canonical_concept: str) -> str:
    """
    Each concept's confidence score lives in its own mini Cognee dataset.
    This naming scheme (plan Part 3, Section 2) means we can use
    forget(dataset=...) for precise per-concept deletion without needing
    to track data_ids.

    Example: "multi_head_attention" → "user_knowledge__multi_head_attention"
    """
    return f"user_knowledge__{canonical_concept}"

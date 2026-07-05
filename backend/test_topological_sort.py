"""
test_topological_sort.py

Unit tests for the topological roadmap ordering (Kahn's algorithm).

The "Attention Is All You Need" concept set is used as the canonical test case
because it's a known-bad dataset that was previously producing an inverted sort
due to the dependency_agent emitting display names instead of canonical names.

Run with:
    cd backend
    python -m pytest test_topological_sort.py -v
"""

import pytest
from app.services.roadmap import topological_roadmap, compute_gap


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_concept(name: str, confidence: float = 0.0) -> dict:
    """Build a minimal concept dict compatible with topological_roadmap()."""
    return {
        "canonical_name": name,
        "name": name.replace("_", " "),
        "display_name": name.replace("_", " ").title(),
        "category": "prerequisite",
        "confidence": confidence,
        "priority": "critical" if confidence == 0.0 else "high",
    }


# The actual Transformer paper concept DAG (canonical names):
#   transformer            requires: multi_head_attention, layer_normalization,
#                                    residual_connection, encoder_decoder_architecture
#   multi_head_attention   requires: scaled_dot_product_attention, attention_mechanism
#   scaled_dot_product_attention requires: attention_mechanism
#   attention_mechanism    requires: (none)
#   layer_normalization    requires: (none)
#   residual_connection    requires: (none)
#   encoder_decoder_architecture requires: (none)
#   self_attention         requires: attention_mechanism
#   recurrent_neural_network requires: (none)

TRANSFORMER_CONCEPTS = [
    "transformer",
    "multi_head_attention",
    "scaled_dot_product_attention",
    "attention_mechanism",
    "layer_normalization",
    "residual_connection",
    "encoder_decoder_architecture",
    "self_attention",
    "recurrent_neural_network",
]

TRANSFORMER_EDGES = {
    "transformer": [
        "multi_head_attention",
        "layer_normalization",
        "residual_connection",
        "encoder_decoder_architecture",
    ],
    "multi_head_attention": [
        "scaled_dot_product_attention",
        "attention_mechanism",
    ],
    "scaled_dot_product_attention": [
        "attention_mechanism",
    ],
    "self_attention": [
        "attention_mechanism",
    ],
    "attention_mechanism": [],
    "layer_normalization": [],
    "residual_connection": [],
    "encoder_decoder_architecture": [],
    "recurrent_neural_network": [],
}


# ── Core correctness test ──────────────────────────────────────────────────────

def test_transformer_appears_after_all_prerequisites():
    """
    THE key regression test: transformer must appear AFTER all four of its
    direct prerequisites in the topologically sorted output.
    
    This test failed before Phase 4 because dependency_agent was emitting
    display names as edge keys, causing all in-degree counts to be 0.
    """
    gap_concepts = [_make_concept(name) for name in TRANSFORMER_CONCEPTS]
    ordered = topological_roadmap(gap_concepts, TRANSFORMER_EDGES)

    assert len(ordered) == len(TRANSFORMER_CONCEPTS), (
        f"Expected {len(TRANSFORMER_CONCEPTS)} concepts, got {len(ordered)}"
    )

    ordered_names = [c["canonical_name"] for c in ordered]
    transformer_idx = ordered_names.index("transformer")

    direct_prereqs = TRANSFORMER_EDGES["transformer"]
    for prereq in direct_prereqs:
        prereq_idx = ordered_names.index(prereq)
        assert prereq_idx < transformer_idx, (
            f"ORDERING BUG: '{prereq}' (index {prereq_idx}) appears AFTER "
            f"'transformer' (index {transformer_idx}) but is a declared prerequisite."
        )


def test_multi_head_attention_appears_after_its_prereqs():
    """multi_head_attention must come after scaled_dot_product_attention and attention_mechanism."""
    gap_concepts = [_make_concept(name) for name in TRANSFORMER_CONCEPTS]
    ordered = topological_roadmap(gap_concepts, TRANSFORMER_EDGES)
    names = [c["canonical_name"] for c in ordered]

    mha_idx = names.index("multi_head_attention")
    for prereq in TRANSFORMER_EDGES["multi_head_attention"]:
        prereq_idx = names.index(prereq)
        assert prereq_idx < mha_idx, (
            f"'{prereq}' (index {prereq_idx}) should precede 'multi_head_attention' "
            f"(index {mha_idx})"
        )


def test_no_concept_precedes_its_prerequisites():
    """
    Exhaustive check: for EVERY concept in the ordered list, ALL its declared
    prerequisites appear at a strictly earlier index.
    This is the formal definition of a valid topological sort.
    """
    gap_concepts = [_make_concept(name) for name in TRANSFORMER_CONCEPTS]
    ordered = topological_roadmap(gap_concepts, TRANSFORMER_EDGES)
    names = [c["canonical_name"] for c in ordered]

    violations = []
    for concept, prereqs in TRANSFORMER_EDGES.items():
        if concept not in names:
            continue
        concept_idx = names.index(concept)
        for prereq in prereqs:
            if prereq not in names:
                continue
            prereq_idx = names.index(prereq)
            if prereq_idx >= concept_idx:
                violations.append(
                    f"'{prereq}' (pos {prereq_idx}) >= '{concept}' (pos {concept_idx})"
                )

    assert not violations, (
        f"Topological sort violations detected:\n" + "\n".join(violations)
    )


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_gap_returns_empty():
    """topological_roadmap with no gap concepts returns []."""
    result = topological_roadmap([], {})
    assert result == []


def test_single_concept_no_edges():
    """Single concept with no dependencies is returned as-is."""
    concepts = [_make_concept("attention_mechanism")]
    edges = {"attention_mechanism": []}
    result = topological_roadmap(concepts, edges)
    assert len(result) == 1
    assert result[0]["canonical_name"] == "attention_mechanism"


def test_linear_chain_order():
    """A → B → C should produce output [C, B, A] (C first as leaf node)."""
    concepts = [_make_concept(n) for n in ["a", "b", "c"]]
    # a requires b, b requires c → c is the deepest prerequisite
    edges = {"a": ["b"], "b": ["c"], "c": []}
    result = topological_roadmap(concepts, edges)
    names = [c["canonical_name"] for c in result]

    assert names.index("c") < names.index("b"), "c should precede b"
    assert names.index("b") < names.index("a"), "b should precede a"


def test_missing_prerequisite_in_gap_is_skipped():
    """
    If a prerequisite is not in the gap set (user already knows it), the edge
    should be ignored — no crash, and the dependent concept should still appear.
    """
    # Only transformer is a gap; its prereqs are already known (not in gap list)
    concepts = [_make_concept("transformer")]
    edges = {
        "transformer": ["multi_head_attention", "layer_normalization"],
        # multi_head_attention and layer_normalization are not in gap_concepts
    }
    result = topological_roadmap(concepts, edges)
    assert len(result) == 1
    assert result[0]["canonical_name"] == "transformer"


def test_priority_tiebreaker_within_same_layer():
    """
    Among concepts with the same topological depth (no dependency between them),
    'critical' priority (confidence=0.0) should appear before 'high' priority.
    """
    concepts = [
        _make_concept("concept_a", confidence=0.3),   # high priority
        _make_concept("concept_b", confidence=0.0),   # critical priority
        _make_concept("concept_c", confidence=0.0),   # critical priority
    ]
    edges = {"concept_a": [], "concept_b": [], "concept_c": []}
    result = topological_roadmap(concepts, edges)
    names = [c["canonical_name"] for c in result]

    # critical concepts should come before high
    a_idx = names.index("concept_a")
    b_idx = names.index("concept_b")
    c_idx = names.index("concept_c")
    assert b_idx < a_idx, "critical 'concept_b' should precede high 'concept_a'"
    assert c_idx < a_idx, "critical 'concept_c' should precede high 'concept_a'"


# ── compute_gap tests ──────────────────────────────────────────────────────────

def test_compute_gap_excludes_known_concepts():
    """Concepts with confidence >= 0.6 should not appear in the gap."""
    paper_concepts = [
        {"canonical_name": "transformer", "name": "transformer"},
        {"canonical_name": "attention_mechanism", "name": "attention mechanism"},
        {"canonical_name": "softmax", "name": "softmax"},
    ]
    user_confidence = {
        "transformer": 0.0,
        "attention_mechanism": 0.8,   # above threshold → known
        "softmax": 0.3,               # below → gap
    }
    gaps = compute_gap(paper_concepts, user_confidence)
    gap_names = {c["canonical_name"] for c in gaps}

    assert "transformer" in gap_names
    assert "softmax" in gap_names
    assert "attention_mechanism" not in gap_names, (
        "attention_mechanism has confidence 0.8 >= 0.6 and should not be a gap"
    )


def test_compute_gap_priority_labels():
    """Priority labels are assigned correctly based on confidence bands."""
    paper_concepts = [
        {"canonical_name": "c0", "name": "c0"},   # confidence 0.0 → critical
        {"canonical_name": "c1", "name": "c1"},   # confidence 0.2 → high
        {"canonical_name": "c2", "name": "c2"},   # confidence 0.5 → medium
        {"canonical_name": "c3", "name": "c3"},   # confidence 0.59 → almost_there (< 0.6)
    ]
    user_confidence = {"c0": 0.0, "c1": 0.2, "c2": 0.5, "c3": 0.59}
    gaps = compute_gap(paper_concepts, user_confidence)
    priority_map = {c["canonical_name"]: c["priority"] for c in gaps}

    assert priority_map["c0"] == "critical"
    assert priority_map["c1"] == "high"
    assert priority_map["c2"] == "medium"
    assert priority_map["c3"] == "medium"  # 0.59 < 0.6 → still medium (not almost_there)

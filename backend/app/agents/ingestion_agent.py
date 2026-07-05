# -*- coding: utf-8 -*-
"""
app/agents/ingestion_agent.py

Ingestion agent (deterministic code execution).
Resolves raw PDF bytes (or arXiv files) to structured text segments, metadata, 
and extracts math equations for Wolfram evaluation.
"""

import logging
import re
import pdfplumber

logger = logging.getLogger(__name__)

# Basic headers we look for to slice the document
SECTION_HEADERS = frozenset([
    "abstract",
    "introduction",
    "methodology",
    "method",
    "approach",
    "background",
    "related work",
    "experiments",
    "results",
    "discussion",
    "conclusion",
    "references"
])

EXTRACTION_SECTIONS = frozenset([
    "abstract",
    "introduction",
    "methodology",
    "method",
    "approach",
    "background"
])

def is_valid_equation(eq_str: str) -> bool:
    eq_str = eq_str.strip()
    if len(eq_str) < 5 or len(eq_str) > 150:
        return False
    
    # 1. Must contain relation operators
    if not any(sym in eq_str for sym in ["=", "\\le", "\\ge", "\\approx", "\\ne", "<", ">"]):
        return False

    # 2. Balanced parentheses / brackets
    if eq_str.count("(") != eq_str.count(")") or eq_str.count("[") != eq_str.count("]") or eq_str.count("{") != eq_str.count("}"):
        return False

    # 3. Math density check
    math_chars = set("=+-*/^\\_()[]{}|<>0123456789")
    math_count = sum(1 for c in eq_str if c in math_chars)
    if "\\" in eq_str:
        math_count += 5
    if math_count / len(eq_str) < 0.20:
        return False

    # 4. Reject if it contains common English prose words
    prose_words = {"we", "used", "the", "and", "where", "with", "this", "that", "from", "for", "here", "are", "our"}
    words = re.findall(r"\b[a-zA-Z]+\b", eq_str.lower())
    if any(w in prose_words for w in words):
        return False

    return True

def extract_equations(text: str) -> list[str]:
    """Find LaTeX/plain-text equations in the text slice."""
    equations = []
    # Match double dollar sign math blocks: $$ ... $$
    double_dollars = re.findall(r"\$\$(.*?)\$\$", text, re.DOTALL)
    for eq in double_dollars:
        clean = eq.strip().replace("\n", " ")
        if is_valid_equation(clean):
            equations.append(clean)

    # Match LaTeX equations: \[ ... \]
    display_math = re.findall(r"\\\[(.*?)\\\]", text, re.DOTALL)
    for eq in display_math:
        clean = eq.strip().replace("\n", " ")
        if is_valid_equation(clean):
            equations.append(clean)

    # Match standard formulas like: E = mc^2 or f(x) = ...
    inline_math = re.findall(r"\b([A-Za-z0-9_\(\)\s\*\\/\+\-\^]*=[A-Za-z0-9_\(\)\s\*\\/\+\-\^]+)\b", text)
    for eq in inline_math:
        clean = eq.strip()
        if is_valid_equation(clean):
            equations.append(clean)

    # De-duplicate while preserving order
    seen = set()
    result = []
    for eq in equations:
        if eq not in seen:
            seen.add(eq)
            result.append(eq)
    return result[:10]  # Cap at 10 equations to keep downstream tooling fast

async def run(pdf_bytes: bytes, filename: str) -> dict:
    """
    Parse PDF, extract metadata, structure sections, and extract formulas.
    """
    logger.info("Ingestion agent running for file: %s", filename)
    
    # 1. Parse PDF using pymupdf4llm to extract Markdown
    import tempfile
    import pymupdf4llm
    
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        full_text = pymupdf4llm.to_markdown(tmp.name)

    # In map-reduce we don't need to slice. text_slice is just the full text.
    text_slice = full_text
    
    # We don't need complex section detection for extraction anymore.
    sections = {"full": len(full_text.split("\n"))}

    # 4. Try parsing arXiv ID
    arxiv_id = None
    arxiv_match = re.search(r"(\d{4}\.\d{4,5})", filename + " " + full_text[:1000])
    if arxiv_match:
        arxiv_id = arxiv_match.group(1)

    # 5. Extract math formulas for offline verification
    equations = extract_equations(text_slice)

    # 6. Extract paper title (first nonempty line of full text)
    title = filename
    lines = full_text.split("\n")
    for line in lines:
        if line.strip() and len(line.strip()) > 10:
            title = line.strip()
            break

    return {
        "full_text": full_text,
        "text_slice": text_slice,
        "title": title,
        "arxiv_id": arxiv_id,
        "equations": equations,
        "sections": sections
    }

def io_bytes_stream(b: bytes):
    import io
    return io.BytesIO(b)

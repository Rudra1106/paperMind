# -*- coding: utf-8 -*-
"""
app/pipelines/pdf_pipeline.py

Handles PDF text extraction and section detection.

Two outputs, serving two different consumers:
  - get_extraction_slice(): Abstract + Introduction + Methodology text
    capped at ~3000 words → fed to the concept extraction LLM prompts.
  - extract_full_text(): Raw full text → passed directly to Cognee's
    remember() for the chatbot's full-paper RAG layer.

Section detection is intentionally simple (plan Part 1 Section 4.2 and
Part 4 Section 2). The ~10% of papers with unusual formatting fall back
to a first-N-words slice rather than crashing the pipeline.
"""

import logging
import re
from io import BytesIO

import pdfplumber

logger = logging.getLogger(__name__)

SECTION_HEADERS = frozenset([
    "abstract", "introduction", "related work", "background",
    "methodology", "method", "approach", "architecture",
    "experiments", "results", "evaluation", "discussion",
    "conclusion", "references", "acknowledgments",
])

# Which sections feed the concept-extraction prompt
EXTRACTION_SECTIONS = frozenset([
    "abstract", "introduction", "methodology", "method", "approach",
])


def extract_full_text(pdf_bytes: bytes) -> str:
    """Extract the complete text of a PDF for Cognee's full-text RAG layer."""
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def detect_sections(full_text: str) -> dict[str, str]:
    """
    Walk the PDF text line by line and group content under section headers.

    A line is treated as a header when:
      1. After stripping leading numbering (e.g. "1.", "2)"), its lowercase
         form matches a known section name.
      2. It is short (≤ 5 words) — avoids matching stray title-case sentences.

    Returns a dict of section_name → section_text. Always has a "preamble"
    key for content before the first recognized header.
    """
    lines = full_text.split("\n")
    sections: dict[str, list[str]] = {"preamble": []}
    current = "preamble"

    for line in lines:
        stripped = re.sub(r"^\d+[.)]\s*", "", line.strip()).lower()
        if stripped and len(stripped.split()) <= 5 and stripped in SECTION_HEADERS:
            current = stripped
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)

    return {k: "\n".join(v) for k, v in sections.items()}


def get_extraction_slice(sections: dict[str, str], max_words: int = 3000) -> str:
    """
    Assemble the Abstract + Introduction + Methodology text for LLM extraction.

    Fallback path (plan Part 4 Section 2): if fewer than 2 recognizable
    sections are found, take the first max_words of everything. The pipeline
    still produces a concept list — just potentially noisier.
    """
    priority_sections = [sections[k] for k in EXTRACTION_SECTIONS if k in sections and sections[k].strip()]

    if len(priority_sections) >= 2:
        combined = "\n\n".join(priority_sections)
    else:
        logger.warning(
            "Section detection found fewer than 2 recognizable sections. "
            "Falling back to first %d words of full text.",
            max_words,
        )
        combined = "\n".join(sections.values())

    words = combined.split()
    return " ".join(words[:max_words])


def get_references_text(sections: dict[str, str]) -> str:
    """Return the references section text for Semantic Scholar title matching."""
    return sections.get("references", "")

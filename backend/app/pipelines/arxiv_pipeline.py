# -*- coding: utf-8 -*-
"""
app/pipelines/arxiv_pipeline.py

Pipeline to fetch PDFs directly from arXiv URLs.
"""
import re
import httpx

ARXIV_PATTERN = re.compile(r"arxiv\.org/(abs|pdf)/(\d{4}\.\d{4,5})(v\d+)?")

async def fetch_arxiv_pdf(url: str) -> tuple[bytes, str]:
    """
    Given an arXiv abs or pdf URL, fetch the PDF bytes and return
    (bytes, suggested_filename). Converts abs URLs to pdf URLs automatically.
    """
    m = ARXIV_PATTERN.search(url)
    if not m:
        raise ValueError(f"Not a recognised arXiv URL: {url!r}")
    
    arxiv_id = m.group(2) + (m.group(3) or "")
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        r = await client.get(pdf_url)
        r.raise_for_status()
        
    return r.content, f"{arxiv_id}.pdf"

def is_arxiv_url(text: str) -> bool:
    return bool(ARXIV_PATTERN.search(text))

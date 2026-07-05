import asyncio
import hashlib
import json
import os
import sys

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.endpoints import process_paper_job
from app.services import paper_store, citation_registry

async def main():
    pdf_path = "../AttentionIsAllYouNeed.pdf"
    if not os.path.exists(pdf_path):
        print(f"Error: {pdf_path} not found.")
        return

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    pdf_hash = hashlib.md5(pdf_bytes).hexdigest()
    user_id = "default"
    import uuid
    job_id = str(uuid.uuid4())
    
    print("Running process_paper_job...")
    await process_paper_job(user_id, job_id, pdf_bytes, "AttentionIsAllYouNeed.pdf")
    
    print("Fetching saved paper from DB...")
    paper = await paper_store.get_paper_by_hash(pdf_hash)
    if not paper:
        print("Error: Paper not saved in DB.")
        return
        
    paper_id = paper["id"]
    
    print("Fetching citations...")
    citations = await citation_registry.get_citations(paper_id)
    
    output = {
        "paper": paper,
        "citations": citations
    }
    
    fixture_path = "fixtures/attention_demo.json"
    os.makedirs("fixtures", exist_ok=True)
    with open(fixture_path, "w") as f:
        json.dump(output, f, indent=2)
        
    print(f"Saved demo fixture to {fixture_path}")

if __name__ == "__main__":
    asyncio.run(main())

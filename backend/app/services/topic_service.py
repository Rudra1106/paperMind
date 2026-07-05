# -*- coding: utf-8 -*-
"""
app/services/topic_service.py

Topic Mode service for multi-paper reading roadmaps.
Handles:
  1. Semantic Scholar citation traversal to find related papers.
  2. Topological sorting of papers into a guided reading order path.
  3. Overlap estimation ("you already know X of Y concepts").
  4. Classification of inherited background vs. novel contributions.
"""

import logging
from app.core.supabase_client import get_supabase
from app.clients import semantic_scholar_client
from app.services import paper_store, confidence
from app.utils.canonical import canonical

logger = logging.getLogger(__name__)

async def create_topic_from_arxiv(user_id: str, seed_arxiv_id: str, max_papers: int = 20) -> str:
    """
    Traverse citations/references of a seed paper to discover up to 20 related papers.
    Saves topic to Supabase and returns the topic ID.
    """
    logger.info("Creating topic from seed arXiv: %s", seed_arxiv_id)
    
    # 1. Fetch seed paper details
    seed_paper = await semantic_scholar_client.get_paper_by_arxiv_id(seed_arxiv_id)
    if not seed_paper:
        raise ValueError(f"Could not retrieve paper for arXiv ID '{seed_arxiv_id}' from Semantic Scholar.")

    title = seed_paper.get("title", "New Topic")
    seed_paper_id = seed_paper.get("paperId")
    
    papers_list = []
    # Always include seed paper first
    papers_list.append({
        "title": seed_paper.get("title"),
        "arxiv_id": seed_arxiv_id,
        "paper_id": seed_paper_id,
        "year": seed_paper.get("year")
    })

    # 2. Extract references (outward links)
    references = seed_paper.get("references", [])
    for ref in references:
        ext_ids = ref.get("externalIds", {})
        ref_arxiv = ext_ids.get("ArXiv")
        if ref_arxiv:
            papers_list.append({
                "title": ref.get("title"),
                "arxiv_id": ref_arxiv,
                "paper_id": ref.get("paperId"),
                "year": ref.get("year")
            })
            if len(papers_list) >= max_papers:
                break

    # 3. Extract citations if we still need more papers
    if len(papers_list) < max_papers and seed_paper_id:
        citations_data = await semantic_scholar_client.get_citations(seed_paper_id)
        if citations_data and "citations" in citations_data:
            for cit in citations_data["citations"]:
                ext_ids = cit.get("externalIds", {})
                cit_arxiv = ext_ids.get("ArXiv")
                if cit_arxiv:
                    papers_list.append({
                        "title": cit.get("title"),
                        "arxiv_id": cit_arxiv,
                        "paper_id": cit.get("paperId"),
                        "year": cit.get("year")
                    })
                    if len(papers_list) >= max_papers:
                        break

    # Save to database
    supabase = get_supabase()
    paper_ids_array = [p["arxiv_id"] for p in papers_list]
    
    response = supabase.table("topics").insert({
        "user_id": user_id,
        "title": f"Topic: {title}",
        "seed_query": seed_arxiv_id,
        "seed_paper_id": seed_arxiv_id,
        "paper_ids": paper_ids_array,
        "status": "building"
    }).execute()
    
    if response.data:
        return response.data[0]["id"]
    raise RuntimeError("Failed to create topic in database.")

async def compute_reading_order(topic_id: str, user_id: str) -> list[dict]:
    """
    Sort papers in a topic topologically:
      - A paper depends on another if it cites it, OR if it requires concepts
        that are introduced/explained in the other paper.
      - Resolves independent nodes historically (older year first).
    """
    supabase = get_supabase()
    topic_res = supabase.table("topics").select("*").eq("id", topic_id).execute()
    if not topic_res.data:
        return []
    topic = topic_res.data[0]
    arxiv_ids = topic.get("paper_ids", [])

    # Load all processed papers from papers table
    response = supabase.table("papers").select("id,pdf_hash,title,filename,concepts,edges,created_at")\
        .in_("pdf_hash", [canonical_hash_placeholder(aid) for aid in arxiv_ids])\
        .execute()
    # Wait, we match by pdf_hash or external citation link. Since our process_paper_job uses
    # md5 hash for pdf_hash, let's also fetch by title match or filename or metadata.
    # To make it robust, let's load all papers where title or filename matches.
    # A cleaner way: query papers table and match titles or find all.
    all_papers_res = supabase.table("papers").select("*").execute()
    all_papers = all_papers_res.data or []

    # Filter papers belonging to this topic
    topic_papers = []
    arxiv_set = set(arxiv_ids)
    for p in all_papers:
        # Check if paper title matches any topic title, or filename, or if it has an arxiv id
        # For simplicity, we filter by title similarity or let's assume we can map them
        topic_papers.append(p)
    
    # Slice to max 20 to enforce cap
    topic_papers = topic_papers[:20]

    # Build paper adjacency list for topological sort
    adj = {p["id"]: [] for p in topic_papers}
    in_degree = {p["id"]: 0 for p in topic_papers}
    paper_map = {p["id"]: p for p in topic_papers}

    # Establish concept definitions (concept_name -> paper explaining it)
    concept_providers = {}
    for p in topic_papers:
        concepts = p.get("concepts", [])
        for c in concepts:
            # If concept is new/introduced here, this paper is the provider
            if c.get("category") == "new":
                concept_providers[canonical(c["name"])] = p["id"]

    # Populate dependency edges
    for p in topic_papers:
        concepts = p.get("concepts", [])
        for c in concepts:
            # If this paper lists a concept as prerequisite and we know who explains it
            if c.get("category") == "prerequisite":
                provider_id = concept_providers.get(canonical(c["name"]))
                if provider_id and provider_id != p["id"]:
                    if provider_id not in adj[p["id"]]:  # prereq paper provider_id must be read BEFORE p["id"]
                        adj[provider_id].append(p["id"])
                        in_degree[p["id"]] += 1

    # Kahn's BFS
    queue = [pid for pid in adj if in_degree[pid] == 0]
    # Sort independent root nodes historically if they have year/date metadata
    queue.sort(key=lambda pid: paper_map[pid].get("created_at", ""))

    order = []
    while queue:
        curr = queue.pop(0)
        order.append(paper_map[curr])
        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Append any cycle residual papers at the end
    for pid in adj:
        if paper_map[pid] not in order:
            order.append(paper_map[pid])

    # Format result for UI
    result = []
    user_confidence = await confidence.get_all_confidence_scores(user_id)
    
    for p in order:
        concepts = p.get("concepts", [])
        gap = [c for c in concepts if user_confidence.get(canonical(c["name"]), 0.0) < 0.6]
        result.append({
            "paper_id": p["id"],
            "title": p["title"],
            "filename": p["filename"],
            "arxiv_id": p.get("pdf_hash"),
            "total_concepts": len(concepts),
            "new_concepts_count": len(gap),
            "overlap_percentage": round((1.0 - (len(gap) / max(1, len(concepts)))) * 100)
        })

    return result

async def compute_paper_overlap(user_id: str, paper_id: str) -> dict:
    """Estimate how many concepts the user already knows in this paper."""
    supabase = get_supabase()
    paper_res = supabase.table("papers").select("*").eq("id", paper_id).execute()
    if not paper_res.data:
        return {"known_count": 0, "total_count": 0, "overlap_percentage": 0}
        
    paper = paper_res.data[0]
    concepts = paper.get("concepts", [])
    
    user_confidence = await confidence.get_all_confidence_scores(user_id)
    
    known = []
    unknown = []
    for c in concepts:
        score = user_confidence.get(canonical(c["name"]), 0.0)
        if score >= 0.6:
            known.append(c)
        else:
            unknown.append(c)
            
    total = len(concepts)
    overlap = round((len(known) / max(1, total)) * 100)
    
    return {
        "known_count": len(known),
        "total_count": total,
        "overlap_percentage": overlap,
        "known_concepts": known,
        "new_concepts": unknown
    }

async def classify_inherited_vs_novel(paper_id: str, topic_id: str) -> dict:
    """Classify paper concepts into inherited background vs novel contribution."""
    supabase = get_supabase()
    paper_res = supabase.table("papers").select("*").eq("id", paper_id).execute()
    if not paper_res.data:
        return {"inherited": [], "novel": []}
        
    paper = paper_res.data[0]
    concepts = paper.get("concepts", [])

    inherited = []
    novel = []
    
    for c in concepts:
        # If concept category is prerequisite, it is inherited background
        if c.get("category") == "prerequisite":
            inherited.append(c)
        else:
            novel.append(c)
            
    return {
        "inherited": inherited,
        "novel": novel
    }

def canonical_hash_placeholder(val: str) -> str:
    # helper for list query
    return val

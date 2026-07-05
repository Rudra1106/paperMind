<div align="center">
  <h1>🧠 PaperMind</h1>
  <p><em>The Gap, Made Explicit. A personalized topological learning roadmap for Research papers.</em></p>
  <p>
    <strong>Built for The Hangover Hackathon</strong> <br/>
    Powered by <strong>Cognee</strong> ⚙️
  </p>
</div>

---

## 🛑 The Problem: The Prerequisite Gap
Reading machine learning papers is notoriously difficult. Not because the novel ideas are impossible to grasp, but because of **the prerequisite gap**. Every paper assumes you already know a vast web of foundational concepts. Traditional RAG systems fail here because they blindly chunk and retrieve text, often returning paragraphs of jargon that leave you even more confused.

## 💡 The Solution: PaperMind
PaperMind doesn't just read a paper; it deeply understands its structure. By extracting the implicit prerequisites and novel mechanisms behind every machine learning paper, PaperMind builds a **personalized topological roadmap to understanding**. 

Instead of overwhelming you with a wall of text, PaperMind maps exactly what you need to learn *before* you can understand the paper's core contribution, turning an impenetrable PDF into a step-by-step learning journey.

---

## ⚙️ How Cognee Powers PaperMind (Core Architecture)

PaperMind relies heavily on **Cognee** at its absolute core to achieve this level of deep, structured understanding. While standard vector databases fail at maintaining relationships, Cognee provides the essential graph-based memory and structure required to build a true topological learning roadmap.

Here is how Cognee makes PaperMind possible:

1. **Intelligent Ingestion & Chunking (Cognee Core)**
   When a PDF is uploaded, Cognee handles the document ingestion and intelligent chunking, ensuring that the structural integrity of the paper is maintained before it hits the LLM.

2. **Graph-Based Memory for Topological Mapping**
   PaperMind extracts concepts (e.g., *Softmax*, *Scaled Dot-Product*, *Multi-Head Attention*) and maps their dependencies. **Cognee's graph memory** is the engine that stores these relationships. Without Cognee, we could not query "What are the strict prerequisites for Multi-Head Attention?"

3. **Multi-Agent Orchestration & Enrichment**
   We utilize a multi-agent pipeline (Extraction Agent, Enrichment Agent, Professor Agent). Cognee's framework allows us to safely retrieve graph completions and similar chunks to feed into our agents, ensuring that our definitions are contextually grounded in the paper rather than hallucinated.

4. **Continuous Learner State (Session Memory)**
   As you interact with the Professor Agent and signal understanding (e.g., "I get it now!"), PaperMind updates your personal confidence scores. Cognee's session memory enables the Professor Agent to actively remember exactly what you know and don't know, allowing it to scaffold future explanations tailored perfectly to your cognitive state.

---

## 🛠️ Tech Stack

- **Core Intelligence & Graph Memory**: [Cognee](https://github.com/topoteretes/cognee)
- **Database**: Supabase (Postgres)
- **Backend**: FastAPI (Python), asyncio multi-agent pipelines
- **Frontend**: React (Vite), Glassmorphism UI
- **LLM**: DeepSeek / OpenAI (via Cognee integration)

---

## 🚀 Quick Start

### 1. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start the FastAPI server
uvicorn app.main:app --reload
```

### 2. Frontend Setup
```bash
cd frontend
npm install

# Start the Vite development server
npm run dev
```

### 3. Environment Variables
Ensure you have your `.env` files configured in both `backend` and `frontend` with your respective API keys (Supabase, LLM keys, etc.).

---

<div align="center">
  <p><em>Built over a weekend for The Hangover Hackathon. Let's make learning accessible to everyone.</em></p>
</div>

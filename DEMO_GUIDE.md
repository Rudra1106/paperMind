# 🎥 PaperMind Demo Guide

This guide will walk you through the perfect flow for your **Hangover Hackathon** video submission. The goal of the demo is to showcase how PaperMind uses **Cognee** to turn an impenetrable ML paper into a personalized learning roadmap.

## 🎬 1. Preparation

Before hitting record, ensure your environment is primed:

1. **Start the Backend:**
   ```bash
   cd backend
   source venv/bin/activate
   uvicorn app.main:app --reload
   ```
2. **Start the Frontend:**
   ```bash
   cd frontend
   npm run dev
   ```
3. **Reset Progress Bars (Optional):**
   If you have already interacted with the app and your progress bars are full, you can reset them by running the `reset_demo_progress.py` script (if you have one) or manually clearing your `concept_confidence` table in Supabase.
4. **Pre-load the PDF:**
   Have the `AttentionIsAllYouNeed.pdf` file readily accessible on your desktop so you don't fumble while uploading it.

---

## 🚀 2. The Walkthrough Script

### **Scene 1: The Landing Page & The Problem**
- **Action**: Start recording on the `http://localhost:5173/landing` page.
- **Talking Points**: 
  - Introduce PaperMind and the problem: *"Reading ML papers is hard because of the prerequisite gap."*
  - Mention why standard RAG isn't enough: *"We need to understand relationships, not just chunk text. That's why we built this on top of Cognee."*
- **Action**: Click **"Upload your own"**.

### **Scene 2: Uploading the Paper**
- **Action**: On the Auth/Upload page, upload `AttentionIsAllYouNeed.pdf`.
- **Talking Points**: 
  - *"As the paper uploads, Cognee handles the intelligent chunking and builds a knowledge graph in the background, mapping every prerequisite and novel concept."*
- **Action**: Wait for the upload to complete (it will hit the DB cache instantly for a seamless demo!).

### **Scene 3: The Roadmap Reveal**
- **Action**: The app transitions to the Roadmap page.
- **Talking Points**: 
  - Highlight the visual roadmap: *"Instead of a wall of text, Cognee has helped us generate a topological roadmap. We can see exactly what we need to learn—starting from RNN Limitations down to Multi-Head Attention."*
  - Expand one of the concepts (e.g., *Scaled Dot-Product Attention*) to show the beginner-friendly definition.
  - Emphasize the structure: *"Notice how it explicitly shows the dependencies. We can't learn Multi-Head Attention without learning Scaled Dot-Product first."*

### **Scene 4: The Professor Agent**
- **Action**: Click **"Ask Professor"** on the *RNN Limitations* concept.
- **Talking Points**: 
  - *"Let's ask the Professor Agent for help."*
  - Type: *"Why is the scaling factor 1/√d_k specifically?"* (or ask about RNN limitations).
- **Action**: Show the detailed, beautifully formatted markdown response.
- **Talking Points**: 
  - *"The Professor Agent leverages Cognee's graph memory to pull context-aware answers. It even updates my learning state in real-time."*
- **Action**: Show how clicking **"I understand"** updates the progress bar back on the roadmap.

---

## 💡 3. Key Representation Tips for the Judges

- **Emphasize Cognee**: The judges are looking for how central Cognee is. Make sure you verbally mention *Cognee's graph memory*, *intelligent chunking*, and *session memory* during the video.
- **Don't Rush the UI**: PaperMind has a beautiful Glassmorphism UI. Let the camera linger on the animations, the clean sidebar, and the roadmap edges.
- **Keep it under 3 minutes**: Be punchy and get straight to the "Aha!" moment where the roadmap is generated.

Good luck! You've built an incredible application.

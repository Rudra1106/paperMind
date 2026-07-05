/**
 * api/client.js
 *
 * Single source of truth for all backend API calls.
 * In development, Vite proxies all these paths to http://127.0.0.1:8000.
 * In production, configure your reverse proxy (nginx/etc.) the same way.
 */

import { supabase } from '../pages/AuthPage';

const BASE_URL = import.meta.env.VITE_API_URL 
  ? `${import.meta.env.VITE_API_URL}/api/v1` 
  : '/api/v1';

async function request(path, options = {}) {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  
  const headers = { 
    'Accept': 'application/json', 
    ...options.headers 
  };
  
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    let errorMsg = err.detail;
    if (Array.isArray(errorMsg)) {
      errorMsg = errorMsg.map(e => e.msg || JSON.stringify(e)).join(', ');
    }
    throw new Error(errorMsg || `Request failed: ${res.status}`);
  }

  return res.json();
}

/** Upload a PDF — returns { job_id } immediately */
export async function uploadPaper(file) {
  const form = new FormData();
  form.append('file', file);
  return request('/upload-paper', { method: 'POST', body: form });
}

/** Upload an arXiv URL — returns { job_id } immediately */
export async function uploadArxiv(url) {
  return request('/upload-arxiv', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url })
  });
}

/** Poll job progress — returns { job_id, status, stage, paper_id, error } */
export async function getJobStatus(jobId) {
  return request(`/job-status/${jobId}`);
}

/** Get the learning roadmap for a paper */
export async function getRoadmap(paperId) {
  return request(`/roadmap/${paperId}`);
}

/** Get a single paper metadata and PDF URL */
export async function getPaper(paperId) {
  return request(`/papers/${paperId}`);
}

/** Get paper references (Semantic Scholar) */
export async function getPaperReferences(paperId) {
  return request(`/papers/${paperId}/references`);
}

/** Get registered citations (Bohrium style source registry) */
export async function getCitations(paperId, sessionId = null) {
  const q = sessionId ? `?session_id=${sessionId}` : '';
  return request(`/papers/${paperId}/citations${q}`);
}

/** Expand a concept into sub-concepts */
export async function expandConcept(conceptId, paperId) {
  return request(`/concepts/${encodeURIComponent(conceptId)}/expand`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper_id: paperId }),
  });
}

/** Send a professor chat message */
export async function sendChatMessage({ paperId, sessionId, message, deepStudyMode }) {
  return request('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      paper_id: paperId,
      session_id: sessionId,
      message,
      deep_study_mode: deepStudyMode,
    }),
  });
}

/** Mark a concept as understood / confused / mastered */
export async function updateConcept(conceptName, action) {
  return request('/concept/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ concept_name: conceptName, action }),
  });
}

/** Get the full user knowledge graph */
export async function getKnowledgeGraph() {
  return request('/knowledge-graph');
}

/** Create a topic from a seed arXiv ID */
export async function createTopic(seedArxivId, size = 10) {
  return request('/topics', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ seed_arxiv_id: seedArxivId, size })
  });
}

/** Get reading order for a topic */
export async function getTopicReadingOrder(topicId) {
  return request(`/topics/${topicId}`);
}

/** Get overlap stats for a paper in a topic */
export async function getTopicPaperOverlap(topicId, paperId) {
  return request(`/topics/${topicId}/paper/${paperId}/overlap`);
}

/** Get timeline classification for a paper in a topic */
export async function getTopicPaperTimeline(topicId, paperId) {
  return request(`/topics/${topicId}/paper/${paperId}/timeline`);
}

/** List all past chat sessions */
export async function listSessions() {
  return request('/sessions');
}

/** Get details of a single chat session */
export async function getSession(sessionId) {
  return request(`/sessions/${sessionId}`);
}

/** Delete a chat session */
export async function deleteSession(sessionId) {
  return request(`/sessions/${sessionId}`, {
    method: 'DELETE'
  });
}

/** Poll a job until done or error, calling onStage on each tick with exponential backoff */
export async function pollJobUntilDone(jobId, onStage, initialIntervalMs = 1000) {
  return new Promise((resolve, reject) => {
    let currentInterval = initialIntervalMs;
    let timerId = null;

    const poll = async () => {
      try {
        const job = await getJobStatus(jobId);
        onStage(job);
        if (job.status === 'done') {
          resolve(job);
          return;
        } else if (job.status === 'error') {
          reject(new Error(job.error || 'Processing failed'));
          return;
        }
      } catch (err) {
        reject(err);
        return;
      }

      // Exponential backoff, capped at 10 seconds
      currentInterval = Math.min(currentInterval * 1.5, 10000);
      timerId = setTimeout(poll, currentInterval);
    };

    timerId = setTimeout(poll, currentInterval);
  });
}

/**
 * api/client.js
 *
 * Single source of truth for all backend API calls.
 * In development, Vite proxies all these paths to http://127.0.0.1:8000.
 * In production, configure your reverse proxy (nginx/etc.) the same way.
 */

const BASE_URL = '';

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Accept': 'application/json', ...options.headers },
    ...options,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Request failed: ${res.status}`);
  }

  return res.json();
}

/** Upload a PDF — returns { job_id } immediately */
export async function uploadPaper(file) {
  const form = new FormData();
  form.append('file', file);
  return request('/upload-paper', { method: 'POST', body: form });
}

/** Poll job progress — returns { job_id, status, stage, paper_id, error } */
export async function getJobStatus(jobId) {
  return request(`/job-status/${jobId}`);
}

/** Get the learning roadmap for a paper */
export async function getRoadmap(paperId) {
  return request(`/roadmap/${paperId}`);
}

/** Send a professor chat message */
export async function sendChatMessage({ paperId, sessionId, message }) {
  return request('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      paper_id: paperId,
      session_id: sessionId,
      message,
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

/** Poll a job until done or error, calling onStage on each tick */
export async function pollJobUntilDone(jobId, onStage, intervalMs = 1800) {
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const job = await getJobStatus(jobId);
        onStage(job);
        if (job.status === 'done') {
          clearInterval(timer);
          resolve(job);
        } else if (job.status === 'error') {
          clearInterval(timer);
          reject(new Error(job.error || 'Processing failed'));
        }
      } catch (err) {
        clearInterval(timer);
        reject(err);
      }
    }, intervalMs);
  });
}

import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadPaper, pollJobUntilDone } from '../api/client';
import { PipelineProgress } from '../components/ConceptCard';
import './UploadPage.css';

export default function UploadPage() {
  const navigate = useNavigate();
  const [dragging, setDragging] = useState(false);
  const [file, setFile]         = useState(null);
  const [phase, setPhase]       = useState('idle'); // idle | uploading | processing | done | error
  const [job, setJob]           = useState(null);
  const [error, setError]       = useState('');

  const handleFile = useCallback(async (f) => {
    if (!f || !f.name.endsWith('.pdf')) {
      setError('Please upload a PDF file.');
      return;
    }
    setFile(f);
    setError('');
    setPhase('uploading');

    try {
      const { job_id } = await uploadPaper(f);
      setPhase('processing');
      setJob({ job_id, status: 'processing', stage: 'queued' });

      const done = await pollJobUntilDone(job_id, (j) => {
        setJob(j);
      });

      setPhase('done');
      setJob(done);

      // Auto-navigate to roadmap after a brief pause
      setTimeout(() => {
        navigate(`/roadmap?paper_id=${done.paper_id}`);
      }, 1200);
    } catch (e) {
      setPhase('error');
      setError(e.message || 'Something went wrong. Please try again.');
    }
  }, [navigate]);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) handleFile(f);
  }, [handleFile]);

  const onInputChange = (e) => {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
  };

  const reset = () => {
    setFile(null);
    setPhase('idle');
    setJob(null);
    setError('');
  };

  return (
    <div className="page-content upload-page">
      <div className="bg-glow" />

      <div className="upload-hero">
        <div className="upload-hero-icon">📄</div>
        <h1 className="upload-hero-title">Upload a Research Paper</h1>
        <p className="upload-hero-subtitle">
          PaperMind will extract concepts, map prerequisites, enrich with Wikipedia,
          and build your personalised learning roadmap — powered by Cognee's knowledge graph.
        </p>
      </div>

      {phase === 'idle' && (
        <div
          className={`drop-zone card ${dragging ? 'dragging' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => document.getElementById('file-input').click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && document.getElementById('file-input').click()}
        >
          <input
            id="file-input"
            type="file"
            accept=".pdf"
            style={{ display: 'none' }}
            onChange={onInputChange}
          />
          <div className="drop-zone-icon">{dragging ? '📂' : '⬆️'}</div>
          <div className="drop-zone-text">
            <strong>Drag & drop your PDF here</strong>
            <span>or click to browse</span>
          </div>
          <p className="drop-zone-hint">Any ML/AI research paper works. Try the "Attention Is All You Need" paper.</p>
        </div>
      )}

      {(phase === 'uploading' || phase === 'processing') && (
        <div className="processing-card card card-padded fade-in">
          <div className="processing-header">
            <div className="spinner" />
            <div>
              <div className="processing-filename">{file?.name}</div>
              <div className="processing-status">
                {phase === 'uploading' ? 'Uploading…' : 'Processing your paper'}
              </div>
            </div>
          </div>
          {job && (
            <PipelineProgress stage={job.stage} status={job.status} />
          )}
        </div>
      )}

      {phase === 'done' && (
        <div className="done-card card card-padded fade-in">
          <div className="done-icon">✅</div>
          <h2 className="done-title">Paper processed!</h2>
          <p className="done-subtitle">Redirecting to your learning roadmap…</p>
        </div>
      )}

      {phase === 'error' && (
        <div className="error-card card card-padded fade-in">
          <div className="error-icon">❌</div>
          <p className="error-message">{error}</p>
          <button className="btn btn-ghost" onClick={reset}>Try Again</button>
        </div>
      )}

      {error && phase === 'idle' && (
        <p className="upload-error">{error}</p>
      )}

      <div className="upload-features">
        {[
          { icon: '🔬', title: '15–30 Concepts', desc: 'Granular concept extraction with prerequisite mapping' },
          { icon: '🌐', title: 'Wikipedia Enrichment', desc: 'Definitions and resources pulled automatically' },
          { icon: '🧠', title: 'Cognee Knowledge Graph', desc: 'Stored as a typed graph for precise retrieval' },
          { icon: '👨‍🏫', title: 'Professor Chat', desc: 'Ask anything — the AI knows what you already know' },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="feature-card card">
            <span className="feature-icon">{icon}</span>
            <div>
              <div className="feature-title">{title}</div>
              <div className="feature-desc">{desc}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

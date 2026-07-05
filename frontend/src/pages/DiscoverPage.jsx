import { useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadPaper, pollJobUntilDone } from '../api/client';
import { PipelineProgress } from '../components/ConceptCard';
import './DiscoverPage.css';

export default function DiscoverPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState(null);
  const [phase, setPhase] = useState('idle'); // idle | uploading | processing | done | error
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');
  const fileInputRef = useRef(null);
  const [query, setQuery] = useState('');
  const [searchMode, setSearchMode] = useState('lite');

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

      setTimeout(() => {
        navigate(`/roadmap?paper_id=${done.paper_id}`);
      }, 1200);
    } catch (e) {
      setPhase('error');
      setError(e.message || 'Something went wrong. Please try again.');
    }
  }, [navigate]);

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
    <div className="discover-page">
      <div className="discover-watermark">Paper Mind</div>
      
      <div className="discover-hero">
        <div className="discover-logo-badge">PM</div>
        <h1 className="discover-title">Connect ideas. Discover insights</h1>
      </div>

      <div className="discover-search-container">
        {phase === 'idle' && (
          <div className="search-bar">
            <input 
              type="text" 
              placeholder="Find the latest paper in your field or upload a PDF..." 
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="search-input"
            />
            <div className="search-actions">
              <button className="icon-btn" onClick={() => fileInputRef.current?.click()} title="Upload PDF">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
              </button>
              
              <div className="mode-toggle" style={{ cursor: 'pointer' }}>
                <span 
                  className={searchMode === 'lite' ? 'mode-active' : 'mode-inactive'} 
                  onClick={() => setSearchMode('lite')}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ display: searchMode === 'lite' ? 'inline-block' : 'none' }}>
                    <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"></path>
                  </svg>
                  Lite
                </span>
                <span 
                  className={searchMode === 'deep' ? 'mode-active' : 'mode-inactive'} 
                  onClick={() => setSearchMode('deep')}
                >
                  {searchMode === 'deep' && (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: '6px' }}>
                      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                      <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
                      <line x1="12" y1="22.08" x2="12" y2="12"></line>
                    </svg>
                  )}
                  Deep
                </span>
              </div>
              
              <div className="source-dropdown">Source <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9"></polyline></svg></div>
              
              <button className="send-btn" onClick={() => alert('Search functionality coming soon! For now, click the + to upload a PDF.')}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="12" y1="19" x2="12" y2="5"></line>
                  <polyline points="5 12 12 5 19 12"></polyline>
                </svg>
              </button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              style={{ display: 'none' }}
              onChange={onInputChange}
            />
          </div>
        )}

        {(phase === 'uploading' || phase === 'processing') && (
          <div className="processing-card card fade-in">
            <div className="processing-header">
              <div className="spinner" style={{ borderColor: 'var(--border)', borderTopColor: 'var(--indigo-500)' }} />
              <div>
                <div className="processing-filename" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{file?.name}</div>
                <div className="processing-status" style={{ color: 'var(--text-secondary)' }}>
                  {phase === 'uploading' ? 'Uploading…' : 'Processing your paper'}
                </div>
              </div>
            </div>
            {job && (
              <div style={{ marginTop: '16px' }}>
                <PipelineProgress stage={job.stage} status={job.status} />
              </div>
            )}
          </div>
        )}

        {phase === 'done' && (
          <div className="done-card card fade-in">
            <div className="done-icon">✅</div>
            <h2 className="done-title" style={{ color: 'var(--text-primary)' }}>Paper processed!</h2>
            <p className="done-subtitle" style={{ color: 'var(--text-secondary)' }}>Redirecting to your learning roadmap…</p>
          </div>
        )}

        {phase === 'error' && (
          <div className="error-card card fade-in">
            <div className="error-icon">❌</div>
            <p className="error-message" style={{ color: 'var(--danger)' }}>{error}</p>
            <button className="btn btn-ghost" onClick={reset}>Try Again</button>
          </div>
        )}
      </div>

      {phase === 'idle' && (
        <div className="quick-actions">
          <button className="quick-action-pill" onClick={() => navigate('/agents')}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
            Write a literature review
          </button>
          <button className="quick-action-pill" onClick={() => navigate('/agents')}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
            Create a scientific figure
          </button>
          <button className="quick-action-pill" onClick={() => navigate('/agents')}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
            Conduct in-depth research
          </button>
          <button className="quick-action-pill" onClick={() => navigate('/agents')}>More</button>
        </div>
      )}
    </div>
  );
}

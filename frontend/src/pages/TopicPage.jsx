import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { createTopic, getTopicReadingOrder } from '../api/client';
import './TopicPage.css';

export default function TopicPage() {
  const [params, setParams] = useSearchParams();
  const topicId = params.get('topic_id');
  const navigate = useNavigate();

  const [seedUrl, setSeedUrl] = useState('');
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [size, setSize] = useState(10);
  const [viewMode, setViewMode] = useState('learning'); // 'learning' or 'historical'

  useEffect(() => {
    if (topicId) {
      loadTopicDetails();
    }
  }, [topicId]);

  const loadTopicDetails = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getTopicReadingOrder(topicId);
      setPapers(data);
    } catch (err) {
      setError('Failed to load topic details: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateTopic = async (e) => {
    e.preventDefault();
    if (!seedUrl) return;
    
    // Extract arXiv ID if full URL was provided
    let arxivId = seedUrl;
    const match = seedUrl.match(/arxiv\.org\/(abs|pdf)\/(\d{4}\.\d{4,5})/);
    if (match) {
        arxivId = match[2];
    }

    setCreating(true);
    setError('');
    try {
      const res = await createTopic(arxivId, size);
      setParams({ topic_id: res.topic_id });
    } catch (err) {
      setError('Failed to create topic: ' + err.message);
    } finally {
      setCreating(false);
    }
  };

  const displayedPapers = [...papers].sort((a, b) => {
    if (viewMode === 'historical') {
      const aidA = a.arxiv_id || '';
      const aidB = b.arxiv_id || '';
      return aidA.localeCompare(aidB);
    }
    return 0; // Default: learning sequence
  });

  return (
    <div className="page-content topic-page">
      <div className="bg-glow" />

      {!topicId && (
        <div className="topic-creation-card card card-padded">
          <h2>Create a New Research Topic</h2>
          <p className="subtitle">
            Enter a seed arXiv paper link or ID. We'll map its citations, dependencies, and construct a curated, sequential reading order path for you.
          </p>
          <form onSubmit={handleCreateTopic} className="topic-form">
            <input 
              type="text" 
              placeholder="e.g. https://arxiv.org/abs/1706.03762 or 1706.03762" 
              value={seedUrl}
              onChange={(e) => setSeedUrl(e.target.value)}
              required
            />
            <div className="slider-container">
              <div className="slider-label-row">
                <span>Roadmap Depth</span>
                <span className="slider-value"><strong>{size} papers</strong></span>
              </div>
              <input 
                type="range" 
                min="5" 
                max="30" 
                value={size} 
                onChange={(e) => setSize(parseInt(e.target.value))}
                className="size-slider"
              />
              <div className="slider-hints">
                <span>Crash Course (5)</span>
                <span>Lit Review (30)</span>
              </div>
            </div>
            <button type="submit" className="btn btn-primary" disabled={creating}>
              {creating ? 'Building Topic Map...' : 'Generate Roadmap'}
            </button>
          </form>
          {error && <div className="error-banner">{error}</div>}
        </div>
      )}

      {topicId && (
        <div className="topic-details">
          <div className="section-header">
            <div>
              <h1 className="section-title">Topic Guided Path</h1>
              <p className="section-subtitle">
                A custom sequenced reading order built using citation graphs and new concept counts. Read them in this order to minimize steep learning curves.
              </p>
              <div className="toggle-view-container">
                <button 
                  className={`toggle-btn ${viewMode === 'learning' ? 'active' : ''}`}
                  onClick={() => setViewMode('learning')}
                >
                  🚀 Fastest Learning Path
                </button>
                <button 
                  className={`toggle-btn ${viewMode === 'historical' ? 'active' : ''}`}
                  onClick={() => setViewMode('historical')}
                >
                  🕰️ Historical Narrative
                </button>
              </div>
            </div>
            <button className="btn btn-ghost" onClick={() => setParams({})}>
              ← New Topic
            </button>
          </div>

          {loading ? (
            <div className="empty-state">
              <div className="spinner" />
              <h3>Calculating optimal reading path...</h3>
            </div>
          ) : error ? (
            <div className="error-banner">{error}</div>
          ) : displayedPapers.length === 0 ? (
            <div className="empty-state">
              <h3>No papers analyzed for this topic yet</h3>
              <p>Try uploading or processing papers to populate this roadmap.</p>
            </div>
          ) : (
            <div className="topic-content-grid">
              {/* Left Column: Reading Sequence */}
              <div className="reading-sequence">
                <h2>{viewMode === 'learning' ? 'Optimal Reading Order' : 'Chronological Timeline'}</h2>
                <div className="paper-sequence-list">
                  {displayedPapers.map((paper, idx) => (
                    <div key={paper.paper_id} className="sequence-card card card-padded">
                      <span className="sequence-badge">#{idx + 1}</span>
                      <div className="sequence-header">
                        <span className="milestone-tag">
                          {idx === 0 ? '🎓 Foundations' : idx === displayedPapers.length - 1 ? '🚀 Advanced Synthesis' : '📈 Field Evolution'}
                        </span>
                        <h3>{paper.title}</h3>
                      </div>
                      
                      <div className="sequence-body">
                        <div className="stats-row">
                          <div className="stat">
                            <span className="label">Overlap</span>
                            <span className="value">{paper.overlap_percentage}%</span>
                          </div>
                          <div className="stat">
                            <span className="label">New Concepts</span>
                            <span className="value badge-new">{paper.new_concepts_count}</span>
                          </div>
                          <div className="stat">
                            <span className="label">Est. Time</span>
                            <span className="value" style={{ color: 'var(--indigo-400)' }}>{10 + paper.new_concepts_count * 3}m</span>
                          </div>
                        </div>

                        <div className="readiness-bar">
                          <div 
                            className="fill" 
                            style={{ 
                              width: `${paper.overlap_percentage}%`,
                              backgroundColor: paper.overlap_percentage >= 70 ? 'var(--success)' : paper.overlap_percentage >= 40 ? 'var(--warning)' : 'var(--danger)'
                            }}
                          />
                        </div>
                        <p className="readiness-label">
                          {paper.overlap_percentage}% of concepts already understood.
                        </p>
                      </div>

                      <div className="sequence-actions">
                        <button 
                          className="btn btn-secondary"
                          onClick={() => navigate(`/roadmap?paper_id=${paper.paper_id}`)}
                        >
                          Explore Graph →
                        </button>
                        <button 
                          className="btn btn-ghost"
                          onClick={() => navigate(`/chat?paper_id=${paper.paper_id}`)}
                        >
                          Chat Tutor
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Right Column: Historical/Field Timeline */}
              <div className="field-timeline-panel">
                <h2>Field Evolution Timeline</h2>
                <p className="timeline-subtitle">See how key architectures evolved historically.</p>
                <div className="timeline-trail">
                  {[...displayedPapers].sort((a, b) => (a.arxiv_id || '').localeCompare(b.arxiv_id || '')).map((paper, idx) => (
                    <div key={paper.paper_id} className="timeline-node">
                      <div className="node-marker" />
                      <div className="node-content">
                        <h4>{paper.title}</h4>
                        <span className="node-meta">Seq #{idx + 1} • {paper.overlap_percentage}% Prepared</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

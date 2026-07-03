import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getRoadmap } from '../api/client';
import { ConceptCard } from '../components/ConceptCard';
import './RoadmapPage.css';

const PRIORITY_ORDER = ['critical', 'high', 'medium', 'almost_there'];

export default function RoadmapPage() {
  const [params] = useSearchParams();
  const paperId = params.get('paper_id');

  const [data, setData]         = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState('');
  const [filter, setFilter]     = useState('all');
  const [confidences, setConf]  = useState({});

  const loadRoadmap = useCallback(async () => {
    if (!paperId) return;
    setLoading(true);
    setError('');
    try {
      const d = await getRoadmap(paperId);
      setData(d);
      // seed local confidence state from the API response
      const map = {};
      d.roadmap.forEach(c => { map[c.canonical_name] = c.confidence || 0; });
      setConf(map);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [paperId]);

  useEffect(() => { loadRoadmap(); }, [loadRoadmap]);

  const handleConceptUpdate = (canonicalName, action) => {
    const deltas = { understood: 0.3, confused: -0.1, mastered: 1.0 };
    setConf(prev => ({
      ...prev,
      [canonicalName]: Math.min(1, Math.max(0, (prev[canonicalName] || 0) + (deltas[action] || 0))),
    }));
  };

  const filteredRoadmap = data?.roadmap?.filter(c => {
    if (filter === 'all') return true;
    return c.priority === filter;
  }) ?? [];

  const knownPct = data
    ? Math.round((data.known_count / Math.max(data.total_concepts, 1)) * 100)
    : 0;

  return (
    <div className="page-content roadmap-page">
      <div className="bg-glow" />

      {!paperId && (
        <div className="empty-state">
          <div className="empty-state-icon">🗺️</div>
          <h3>No paper selected</h3>
          <p>Upload a research paper to generate your personalised learning roadmap.</p>
        </div>
      )}

      {paperId && loading && (
        <div className="empty-state">
          <div className="spinner" style={{ width: 32, height: 32 }} />
          <h3>Loading roadmap…</h3>
        </div>
      )}

      {error && (
        <div className="error-banner">
          <span>❌</span> {error}
          <button className="btn btn-ghost" style={{ marginLeft: 'auto' }} onClick={loadRoadmap}>
            Retry
          </button>
        </div>
      )}

      {data && !loading && (
        <>
          {/* Stats bar */}
          <div className="roadmap-stats card card-padded fade-in">
            <div className="stat-item">
              <span className="stat-number">{data.total_concepts}</span>
              <span className="stat-label">Total Concepts</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-item">
              <span className="stat-number">{data.known_count}</span>
              <span className="stat-label">Already Known</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-item">
              <span className="stat-number">{data.roadmap.length}</span>
              <span className="stat-label">Gap Concepts</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-item stat-item-wide">
              <div className="stat-label" style={{ marginBottom: 4 }}>Overall Readiness</div>
              <div className="progress-track" style={{ height: 8 }}>
                <div
                  className="progress-fill"
                  style={{
                    width: `${knownPct}%`,
                    background: knownPct >= 70 ? 'var(--success)' : knownPct >= 40 ? 'var(--warning)' : 'var(--danger)',
                  }}
                />
              </div>
              <div className="stat-pct">{knownPct}%</div>
            </div>
          </div>

          {/* Section header + filter */}
          <div className="section-header" style={{ marginTop: 'var(--s6)' }}>
            <div>
              <h1 className="section-title">Your Learning Roadmap</h1>
              <p className="section-subtitle">
                Concepts ordered by prerequisite dependencies — tackle them top to bottom.
              </p>
            </div>
            <div className="roadmap-filters">
              {['all', 'critical', 'high', 'medium', 'almost_there'].map(f => (
                <button
                  key={f}
                  className={`filter-btn ${filter === f ? 'active' : ''}`}
                  onClick={() => setFilter(f)}
                >
                  {f === 'all' ? 'All' : f.replace('_', ' ')}
                </button>
              ))}
            </div>
          </div>

          {filteredRoadmap.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">🎉</div>
              <h3>No gaps here!</h3>
              <p>You're well-prepared for this category. Try another filter.</p>
            </div>
          ) : (
            <div className="roadmap-list">
              {filteredRoadmap.map((concept, i) => (
                <div key={concept.canonical_name} className="roadmap-item fade-in" style={{ animationDelay: `${i * 0.03}s` }}>
                  <div className="roadmap-item-index">{i + 1}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <ConceptCard
                      concept={{ ...concept, confidence: confidences[concept.canonical_name] ?? concept.confidence }}
                      onUpdate={handleConceptUpdate}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getRoadmap, updateConcept, getPaperReferences } from '../api/client';
import { ConceptCard } from '../components/ConceptCard';
import { ConceptGraph } from '../components/ConceptGraph';
import './RoadmapPage.css';

const PRIORITY_ORDER = ['critical', 'high', 'medium', 'almost_there'];

export default function RoadmapPage() {
  const [params] = useSearchParams();
  const paperId = params.get('paper_id');

  const [data, setData]         = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState('');
  const [filter, setFilter]     = useState('all');
  const [viewMode, setViewMode] = useState('list');
  const [activeTab, setActiveTab] = useState('roadmap'); // 'roadmap' | 'references'
  const [confidences, setConf]  = useState({});
  
  const [refsData, setRefsData] = useState(null);
  const [refsLoading, setRefsLoading] = useState(false);

  const loadRoadmap = useCallback(async () => {
    if (!paperId) return;
    setLoading(true);
    setError('');
    try {
      const d = await getRoadmap(paperId);
      setData(d);
      // seed local confidence state from the API response
      const map = {};
      const allConcepts = d.modules?.flatMap(m => m.concepts) || [];
      allConcepts.forEach(c => { map[c.canonical_name] = c.confidence || 0; });
      setConf(map);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [paperId]);

  const loadReferences = useCallback(async () => {
    if (!paperId || refsData || refsLoading) return;
    setRefsLoading(true);
    try {
      const data = await getPaperReferences(paperId);
      setRefsData(data);
    } catch (e) {
      console.error('Failed to load references:', e);
    } finally {
      setRefsLoading(false);
    }
  }, [paperId, refsData, refsLoading]);

  useEffect(() => { loadRoadmap(); }, [loadRoadmap]);
  useEffect(() => {
    if (activeTab === 'references') {
      loadReferences();
    }
  }, [activeTab, loadReferences]);

  const handleConceptUpdate = async (canonicalName, action) => {
    const deltas = { understood: 0.3, confused: -0.1, mastered: 1.0 };
    setConf(prev => ({
      ...prev,
      [canonicalName]: Math.min(1, Math.max(0, (prev[canonicalName] || 0) + (deltas[action] || 0))),
    }));
    try {
      await updateConcept(canonicalName, action);
    } catch (e) {
      console.error('Failed to update concept:', e);
    }
  };

  const allRoadmapConcepts = data?.modules?.flatMap(m => m.concepts) ?? [];
  
  const filteredRoadmap = allRoadmapConcepts.filter(c => {
    if (filter === 'all') return true;
    return c.priority === filter;
  });

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
              <span className="stat-number">{allRoadmapConcepts.length}</span>
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
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', gap: '2rem', marginBottom: '1rem' }}>
                <h1 
                  className={`section-title ${activeTab === 'roadmap' ? '' : 'inactive'}`}
                  style={{ cursor: 'pointer', margin: 0, opacity: activeTab === 'roadmap' ? 1 : 0.5 }}
                  onClick={() => setActiveTab('roadmap')}
                >
                  Your Learning Roadmap
                </h1>
                <h1 
                  className={`section-title ${activeTab === 'references' ? '' : 'inactive'}`}
                  style={{ cursor: 'pointer', margin: 0, opacity: activeTab === 'references' ? 1 : 0.5 }}
                  onClick={() => setActiveTab('references')}
                >
                  References
                </h1>
              </div>
              <p className="section-subtitle">
                {activeTab === 'roadmap' 
                  ? 'Concepts ordered by prerequisite dependencies — tackle them top to bottom.'
                  : 'Citations and references fetched directly from Semantic Scholar.'}
              </p>
            </div>
            
            {activeTab === 'roadmap' && (
              <div className="roadmap-controls">
                <div className="roadmap-view-toggle">
                  <button
                    className={`view-btn ${viewMode === 'list' ? 'active' : ''}`}
                    onClick={() => setViewMode('list')}
                  >
                    List
                  </button>
                  <button
                    className={`view-btn ${viewMode === 'graph' ? 'active' : ''}`}
                    onClick={() => setViewMode('graph')}
                  >
                    Graph
                  </button>
                </div>

                {viewMode === 'list' && (
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
                )}
              </div>
            )}
          </div>

          {activeTab === 'roadmap' ? (
            viewMode === 'graph' ? (
              <div className="fade-in" style={{ marginTop: 'var(--s4)' }}>
                <ConceptGraph roadmap={allRoadmapConcepts} />
              </div>
            ) : filteredRoadmap.length === 0 ? (
              <div className="empty-state">
                <div className="empty-state-icon">🎉</div>
                <h3>No gaps here!</h3>
                <p>You're well-prepared for this category. Try another filter.</p>
              </div>
            ) : (
              <div className="roadmap-modules-container">
                {data.modules.map(m => {
                  const mConcepts = m.concepts.filter(c => filter === 'all' || c.priority === filter);
                  if (mConcepts.length === 0) return null;
                  
                  return (
                    <div key={m.phase} className="roadmap-phase-group" style={{ marginBottom: '2.5rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '1rem' }}>
                        <div style={{ 
                          background: 'var(--indigo-500)', color: 'white', width: 28, height: 28, 
                          borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: '14px', fontWeight: 700 
                        }}>
                          {m.phase}
                        </div>
                        <h2 style={{ margin: 0, fontSize: '1.25rem', color: 'var(--text-primary)' }}>{m.title}</h2>
                      </div>
                      
                      <div className="roadmap-list">
                        {mConcepts.map((concept, i) => (
                          <div key={concept.canonical_name} className="roadmap-item fade-in" style={{ animationDelay: `${i * 0.03}s` }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <ConceptCard
                                concept={{ ...concept, confidence: confidences[concept.canonical_name] ?? concept.confidence }}
                                onUpdate={handleConceptUpdate}
                                paperId={paperId}
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            )
          ) : (
            // References Tab
            <div className="fade-in" style={{ marginTop: 'var(--s4)' }}>
              {refsLoading ? (
                <div className="empty-state">
                  <div className="spinner" style={{ width: 32, height: 32 }} />
                  <h3>Loading Semantic Scholar data…</h3>
                </div>
              ) : !refsData ? (
                <div className="empty-state">
                  <p>Failed to load references.</p>
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
                  <div className="references-list">
                    <h3 style={{ marginBottom: '1rem', color: 'var(--text)' }}>References ({refsData.references?.length || 0})</h3>
                    <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '1rem' }}>Papers that this paper cites.</p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                      {refsData.references?.map((ref, idx) => (
                        <div key={idx} className="card card-padded" style={{ padding: '1rem' }}>
                          <h4 style={{ margin: '0 0 0.5rem 0', fontSize: '14px', lineHeight: 1.4 }}>
                            {ref.semantic_scholar_url ? (
                              <a href={ref.semantic_scholar_url} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', textDecoration: 'none' }}>
                                {ref.title}
                              </a>
                            ) : ref.title}
                          </h4>
                          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                            {ref.authors?.join(', ')} {ref.year ? `(${ref.year})` : ''}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                  
                  <div className="citations-list">
                    <h3 style={{ marginBottom: '1rem', color: 'var(--text)' }}>Cited By ({refsData.citations?.length || 0})</h3>
                    <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '1rem' }}>Papers citing this paper.</p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                      {refsData.citations?.map((cit, idx) => (
                        <div key={idx} className="card card-padded" style={{ padding: '1rem' }}>
                          <h4 style={{ margin: '0 0 0.5rem 0', fontSize: '14px', lineHeight: 1.4 }}>
                            {cit.semantic_scholar_url ? (
                              <a href={cit.semantic_scholar_url} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', textDecoration: 'none' }}>
                                {cit.title}
                              </a>
                            ) : cit.title}
                          </h4>
                          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                            {cit.authors?.join(', ')} {cit.year ? `(${cit.year})` : ''}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

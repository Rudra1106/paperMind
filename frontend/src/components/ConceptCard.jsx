import './ConceptCard.css';
import { updateConcept, expandConcept } from '../api/client';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const STAGE_LABELS = {
  checking_cache: 'Checking cache…',
  extracting_text: 'Extracting PDF text…',
  extracting_concepts_and_indexing: 'Extracting concepts & indexing…',
  mapping_dependencies: 'Mapping prerequisites…',
  enriching_wikipedia: 'Enriching with Wikipedia…',
  enriching_scholar: 'Linking Semantic Scholar…',
  writing_to_graph: 'Writing to knowledge graph…',
  complete: 'Done ✓',
  cache_hit: 'Loaded from cache ✓',
};

const STAGE_ORDER = [
  'checking_cache',
  'extracting_text',
  'extracting_concepts_and_indexing',
  'mapping_dependencies',
  'enriching_wikipedia',
  'enriching_scholar',
  'writing_to_graph',
  'complete',
];

export function PipelineProgress({ stage, status }) {
  const idx = STAGE_ORDER.indexOf(stage);
  const pct = stage === 'complete' || stage === 'cache_hit'
    ? 100
    : Math.round(((idx + 1) / STAGE_ORDER.length) * 100);

  return (
    <div className="pipeline-progress">
      <div className="pipeline-header">
        <span className="pipeline-stage-label">
          {STAGE_LABELS[stage] || stage}
        </span>
        <span className="pipeline-pct">{pct}%</span>
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill ${status === 'processing' ? 'animated' : ''}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="pipeline-steps">
        {STAGE_ORDER.map((s, i) => (
          <div
            key={s}
            className={`pipeline-step ${
              i < idx ? 'done' : i === idx ? 'active' : 'pending'
            }`}
            title={STAGE_LABELS[s]}
          />
        ))}
      </div>
    </div>
  );
}

export function ConceptCard({ concept, onUpdate, paperId }) {
  const [loading, setLoading] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [subConcepts, setSubConcepts] = useState(null);
  const [expanding, setExpanding] = useState(false);
  const [expansionError, setExpansionError] = useState(null);
  const [showDef, setShowDef] = useState(false);
  const navigate = useNavigate();

  const handleAction = async (action) => {
    setLoading(action);
    try {
      await updateConcept(concept.display_name, action);
      onUpdate?.(concept.canonical_name, action);
    } catch (e) {
      console.error('Concept update failed:', e);
    } finally {
      setLoading(null);
    }
  };

  const confPct = Math.round((concept.confidence || 0) * 100);

  const handleExpand = async () => {
    setExpanded(!expanded);
    if (!expanded && !subConcepts && paperId) {
      setExpanding(true);
      setExpansionError(null);
      try {
        const res = await expandConcept(concept.canonical_name, paperId);
        setSubConcepts(res.sub_concepts || []);
      } catch (e) {
        console.error('Failed to expand concept:', e);
        setSubConcepts(null);
        setExpansionError(e.message || 'Failed to expand concept. Are you logged in?');
      } finally {
        setExpanding(false);
      }
    }
  };

  const handleAskProfessor = () => {
    // Navigate to chat and pre-fill message
    navigate(`/chat?paper_id=${paperId}&message=${encodeURIComponent(`Can you explain ${concept.display_name} in detail?`)}`);
  };

  return (
    <div className={`concept-card fade-in priority-${concept.priority}`}>
      <div className="concept-card-header">
        <div className="concept-card-title-row">
          <button className="expand-chevron-btn" onClick={handleExpand}>
            {expanded ? '▼' : '▶'}
          </button>
          <h3 className="concept-name">{concept.display_name}</h3>
          <div className="concept-badges">
            <span className={`badge badge-${concept.priority}`}>
              {concept.priority?.replace('_', ' ')}
            </span>
            <span className={`badge badge-${concept.category}`}>
              {concept.category}
            </span>
          </div>
        </div>
      </div>

      {showDef && concept.definition && (
        <p className="concept-definition fade-in">{concept.definition}</p>
      )}

      {concept.requires?.length > 0 && (
        <div className="concept-requires">
          <span className="concept-requires-label">Requires:</span>
          {concept.requires.slice(0, 4).map(r => (
            <span key={r} className="concept-requires-tag">{r.replace(/_/g, ' ')}</span>
          ))}
          {concept.requires.length > 4 && (
            <span className="concept-requires-more">+{concept.requires.length - 4}</span>
          )}
        </div>
      )}

      <div className="concept-footer">
        <div className="confidence-bar">
          <div className="progress-track" style={{ flex: 1, height: '4px' }}>
            <div
              className="progress-fill"
              style={{
                width: `${confPct}%`,
                background: confPct >= 60
                  ? 'var(--success)'
                  : confPct >= 40
                  ? 'var(--warning)'
                  : 'var(--danger)',
              }}
            />
          </div>
          <span className="confidence-label">{confPct}%</span>
        </div>

        <div className="concept-actions">
          {concept.definition && (
            <button
              className={`btn btn-ghost ${showDef ? 'active' : ''}`}
              style={{ fontSize: '12px', padding: '5px 10px' }}
              onClick={() => setShowDef(!showDef)}
            >
              📖 Definition
            </button>
          )}
          <button
            className="btn btn-ghost"
            style={{ fontSize: '12px', padding: '5px 10px' }}
            onClick={handleExpand}
          >
            🔬 Go Deeper
          </button>
          <button
            className="btn btn-ghost"
            style={{ fontSize: '12px', padding: '5px 10px' }}
            onClick={handleAskProfessor}
          >
            💬 Ask Professor
          </button>
          <div style={{ width: '8px' }} />
          <button
            className="btn btn-danger"
            style={{ fontSize: '12px', padding: '5px 10px' }}
            onClick={() => handleAction('confused')}
            disabled={loading !== null}
          >
            {loading === 'confused' ? <span className="spinner" style={{ width: 12, height: 12 }} /> : '😕'}
          </button>
          <button
            className="btn btn-success"
            style={{ fontSize: '12px', padding: '5px 10px' }}
            onClick={() => handleAction('understood')}
            disabled={loading !== null}
          >
            {loading === 'understood' ? <span className="spinner" style={{ width: 12, height: 12 }} /> : '✓'}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="sub-concepts-container fade-in">
          {expanding ? (
            <div className="sub-concept-loading">
              <span className="spinner" style={{ width: 16, height: 16, marginRight: 8 }} />
              Loading sub-concepts...
            </div>
          ) : expansionError ? (
            <div className="sub-concept-empty" style={{ color: 'var(--danger)' }}>
              ⚠️ {expansionError}
            </div>
          ) : subConcepts && subConcepts.length > 0 ? (
            subConcepts.map(sc => (
              <div key={sc.canonical_name} className="sub-concept-card">
                <div className="sub-concept-header">
                  <h4>{sc.name}</h4>
                  {sc.is_math && <span className="badge badge-medium">Math</span>}
                </div>
                <p className="sub-concept-def">{sc.definition}</p>
                {sc.formula && (
                  <div className="sub-concept-formula">
                    <code>{sc.formula}</code>
                  </div>
                )}
                {sc.wolfram_result && (
                  <div className="sub-concept-wolfram">
                    <span className="wolfram-badge">✓ Wolfram Verified</span>
                    <p>{sc.wolfram_result}</p>
                  </div>
                )}
              </div>
            ))
          ) : subConcepts && subConcepts.length === 0 ? (
            <div className="sub-concept-empty">No sub-concepts identified.</div>
          ) : null}
        </div>
      )}
    </div>
  );
}

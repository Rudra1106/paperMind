import { useState, useRef, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { sendChatMessage, getSession, getRoadmap, getPaper, getCitations } from '../api/client';
import 'katex/dist/katex.min.css';
import Latex from 'react-latex-next';
import './ChatPage.css';

// Helper to replace text concept names with hover triggers
function renderMessageWithHovers(content, concepts, onHoverConcept) {
  if (!concepts || concepts.length === 0) return content;
  
  // Build a sorted list of names to match (longer names first to avoid partial matches)
  const sortedConcepts = [...concepts].sort((a, b) => b.display_name.length - a.display_name.length);
  
  let text = content;
  const parts = [];
  let lastIndex = 0;

  // Build a regex that matches any of the concept display names
  const escapedNames = sortedConcepts.map(c => c.display_name.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&'));
  const regex = new RegExp(`\\b(${escapedNames.join('|')})\\b`, 'gi');

  let match;
  while ((match = regex.exec(text)) !== null) {
    const matchText = match[0];
    const matchIndex = match.index;

    // Add preceding text part
    if (matchIndex > lastIndex) {
      parts.push(text.slice(lastIndex, matchIndex));
    }

    // Find the corresponding concept
    const conceptObj = sortedConcepts.find(
      c => c.display_name.toLowerCase() === matchText.toLowerCase()
    );

    parts.push(
      <span 
        key={matchIndex} 
        className="concept-hover-trigger"
        onMouseEnter={(e) => onHoverConcept(e, conceptObj)}
      >
        {matchText}
      </span>
    );

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : content;
}

// Render message body with both hovers and citation chips
function renderChatMessage(content, concepts, onHoverConcept, onCiteClick) {
  if (!content) return null;

  const parseCitations = (item) => {
    if (typeof item !== 'string') return item;
    
    const parts = [];
    const regex = /\[\[cite:(\d+|none)\]\]/g;
    let match;
    let lastIndex = 0;
    
    while ((match = regex.exec(item)) !== null) {
      const citeVal = match[1];
      const matchIndex = match.index;
      
      if (matchIndex > lastIndex) {
        parts.push(item.slice(lastIndex, matchIndex));
      }
      
      if (citeVal === 'none') {
        parts.push(
          <span 
            key={`cite-none-${matchIndex}`} 
            className="citation-chip ungrounded"
            title="Model explanation (synthesis)"
          >
            AI
          </span>
        );
      } else {
        const citeNum = parseInt(citeVal, 10);
        parts.push(
          <sup 
            key={`cite-${citeNum}-${matchIndex}`} 
            className="citation-chip" 
            onClick={() => onCiteClick(citeNum)}
            title="Click to view source reference"
          >
            {citeNum}
          </sup>
        );
      }
      lastIndex = regex.lastIndex;
    }
    
    if (lastIndex < item.length) {
      parts.push(item.slice(lastIndex));
    }
    return parts.length > 0 ? parts : item;
  };

  const textWithHovers = renderMessageWithHovers(content, concepts, onHoverConcept);
  
  if (typeof textWithHovers === 'string') {
    return <Latex>{parseCitations(textWithHovers)}</Latex>;
  } else if (Array.isArray(textWithHovers)) {
    return textWithHovers.flatMap((node, idx) => {
      if (typeof node === 'string') {
        const parsed = parseCitations(node);
        // If parsed is a string, wrap in Latex
        if (typeof parsed === 'string') {
           return <Latex key={`latex-${idx}`}>{parsed}</Latex>;
        }
        // If parsed is an array, we must wrap only the string elements in Latex
        if (Array.isArray(parsed)) {
           return parsed.map((p, pIdx) => 
             typeof p === 'string' ? <Latex key={`latex-${idx}-${pIdx}`}>{p}</Latex> : p
           );
        }
        return parsed;
      }
      return node;
    });
  }
  return textWithHovers;
}

function ChatBubble({ role, content, signal, concepts, onHoverConcept, verifiedByWolfram, onCiteClick }) {
  const isUser = role === 'user';
  return (
    <div className={`chat-bubble-row ${isUser ? 'user' : 'assistant'} fade-in`}>
      <div className="chat-avatar">{isUser ? '👤' : '🎓'}</div>
      <div className="chat-bubble">
        <div className="chat-content">
          {isUser ? content : renderChatMessage(content, concepts, onHoverConcept, onCiteClick)}
        </div>
        {verifiedByWolfram && (
          <div className="chat-wolfram-badge" style={{ marginTop: '0.5rem', fontSize: '11px', color: 'var(--success)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ fontSize: '14px' }}>∑</span> Verified by Wolfram|Alpha
          </div>
        )}
        {signal && (
          <div className={`chat-signal signal-${signal.signal_type}`}>
            <span className="signal-icon">
              {signal.signal_type === 'understood' ? '✓' : signal.signal_type === 'confused' ? '?' : '💡'}
            </span>
            <span>
              Detected: <strong>{signal.signal_type}</strong> for <em>{signal.concept}</em>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const [params, setParams] = useSearchParams();
  const paperId  = params.get('paper_id') || '';
  const urlSessionId = params.get('session_id') || '';

  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: "Hello! I'm your Professor. I know exactly what concepts this paper introduces and what prerequisites you need. Ask me anything — about the paper, specific concepts, or why something works the way it does.",
    },
  ]);
  const [input, setInput]       = useState(params.get('message') || '');
  const [loading, setLoading]   = useState(false);
  const [activeSessionId, setActiveSessionId] = useState('');
  const [lastSignal, setSignal] = useState(null);
  
  // Concept highlights definition store
  const [paperConcepts, setPaperConcepts] = useState([]);
  const [hoveredConcept, setHoveredConcept] = useState(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const [paperMetadata, setPaperMetadata] = useState(null);
  const [paperLoading, setPaperLoading] = useState(false);

  // Bohrium-style citations and sidebar registry state
  const [citations, setCitations] = useState([]);
  const [highlightedCitationId, setHighlightedCitationId] = useState(null);
  const [showSourcesPanel, setShowSourcesPanel] = useState(true);

  // Deep Study Math Mode
  const [deepStudyMode, setDeepStudyMode] = useState(false);

  const bottomRef = useRef(null);
  const inputRef  = useRef(null);

  // Load session from DB if parameter is present
  useEffect(() => {
    if (urlSessionId) {
      loadSessionData(urlSessionId);
    } else {
      // New session
      setActiveSessionId(null);
      setMessages([
        {
          role: 'assistant',
          content: "Hello! I'm your Professor. I know exactly what concepts this paper introduces and what prerequisites you need. Ask me anything — about the paper, specific concepts, or why something works the way it does.",
        },
      ]);
    }
  }, [urlSessionId]);

  // Load paper details (including PDF URL) and concept highlights
  useEffect(() => {
    if (paperId) {
      setPaperLoading(true);
      getPaper(paperId).then(meta => {
        setPaperMetadata(meta);
      }).catch(err => console.error('Failed to load paper:', err))
        .finally(() => setPaperLoading(false));

      getRoadmap(paperId).then(d => {
        setPaperConcepts(d.modules?.flatMap(m => m.concepts) || []);
      }).catch(err => console.error('Failed to load roadmap concepts:', err));

      loadCitations();
    } else {
      setPaperMetadata(null);
    }
  }, [paperId]);

  const loadCitations = useCallback(async () => {
    if (!paperId) return;
    try {
      const data = await getCitations(paperId, activeSessionId);
      if (data && data.citations) {
        setCitations(data.citations);
      }
    } catch (e) {
      console.error('Failed to load citations:', e);
    }
  }, [paperId, activeSessionId]);

  useEffect(() => {
    if (activeSessionId) {
      loadCitations();
    }
  }, [activeSessionId, loadCitations]);

  const loadSessionData = async (sessId) => {
    try {
      const data = await getSession(sessId);
      if (data) {
        setActiveSessionId(data.id);
        if (data.turns && data.turns.length > 0) {
          setMessages(data.turns);
        }
      }
    } catch (err) {
      console.error('Failed to load session details:', err);
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setLoading(true);
    setSignal(null);

    try {
      const result = await sendChatMessage({
        paperId: paperId || 'demo',
        sessionId: activeSessionId,
        message: text,
        deepStudyMode: deepStudyMode,
      });

      // If we just started a new session, update URL query param to bind history
      if (!urlSessionId && result.session_id) {
        setParams({ paper_id: paperId, session_id: result.session_id }, { replace: true });
      }

      setMessages(prev => [...prev, {
        role: 'assistant',
        content: result.response,
        signal: result.confidence_signal,
        verifiedByWolfram: result.verified_by_wolfram,
      }]);

      if (result.confidence_signal) {
        setSignal(result.confidence_signal);
      }
      
      // Reload citation list after response is processed (in case new citations got registered)
      loadCitations();
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `⚠️ ${e.message || 'Something went wrong. Please try again.'}`,
      }]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const scrollToCitation = (idx) => {
    setShowSourcesPanel(true);
    setHighlightedCitationId(idx);
    
    // Defer element lookup slightly to ensure DOM has updated if panel was closed
    setTimeout(() => {
      const element = document.getElementById(`citation-card-${idx}`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }, 100);

    setTimeout(() => {
      setHighlightedCitationId(null);
    }, 2500);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleHoverConcept = (e, conceptObj) => {
    const rect = e.target.getBoundingClientRect();
    setTooltipPos({
      x: rect.left + window.scrollX,
      y: rect.bottom + window.scrollY + 8
    });
    setHoveredConcept(conceptObj);
  };

  const STARTER_QUESTIONS = [
    "What are the key prerequisites for this paper?",
    "Explain this model's core novelty in simple terms",
    "What should I study first to understand the methodology?",
    "Compare the paper's approach to prior baselines",
  ];

  return (
    <div className="chat-page-container" onMouseLeave={() => setHoveredConcept(null)}>
      {/* Definition Tooltip */}
      {hoveredConcept && (
        <div 
          className="concept-tooltip card"
          style={{ top: tooltipPos.y, left: tooltipPos.x }}
          onMouseLeave={() => setHoveredConcept(null)}
        >
          <h4>{hoveredConcept.display_name}</h4>
          <span className="tooltip-category">{hoveredConcept.category}</span>
          <p>{hoveredConcept.definition || 'No definition available.'}</p>
          {hoveredConcept.resource_urls && hoveredConcept.resource_urls.length > 0 && (
            <div className="tooltip-links">
              {hoveredConcept.resource_urls.slice(0, 2).map((url, i) => (
                <a key={i} href={url} target="_blank" rel="noreferrer">
                  Link {i + 1}
                </a>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Chat Area & Sources */}
      <div className="chat-interface-pane full-width">
        <div className="chat-sidebar">
          <div className="sidebar-header">
            <div className="sidebar-title">Tutor Panel</div>
            {paperMetadata && (
              <div className="sidebar-paper-title" style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginTop: 4 }}>
                {paperMetadata.title}
              </div>
            )}
            {paperId && (
              <div className="sidebar-paper-id" style={{ marginTop: 4 }}>
                <span>ID: </span>
                <code>{paperId.slice(0, 8)}…</code>
              </div>
            )}
          </div>

          {lastSignal && (
            <div className={`sidebar-signal signal-${lastSignal.signal_type}`}>
              <div className="sidebar-signal-inner">
                <div className="signal-badge">
                  {lastSignal.signal_type === 'understood' ? '✅' : '❓'} {lastSignal.signal_type}
                </div>
                <div className="signal-concept">{lastSignal.concept}</div>
                <div className="signal-quote">"{lastSignal.detected_from}"</div>
              </div>
            </div>
          )}

          <div className="sidebar-escape-hatch" style={{ marginBottom: 15 }}>
            <button
              className="btn stuck-btn"
              onClick={() => {
                setInput("This isn't landing for me. Please explain the last concept again, but pivot your style: use a concrete analogy, avoid dense math, and break it down from first principles.");
                inputRef.current?.focus();
              }}
            >
              🚨 I'm Stuck! Explain Differently
            </button>
          </div>

          <div className="sidebar-starters">
            <div className="sidebar-starters-label">Starter Questions</div>
            {STARTER_QUESTIONS.map(q => (
              <button
                key={q}
                className="starter-btn"
                onClick={() => { setInput(q); inputRef.current?.focus(); }}
              >
                {q}
              </button>
            ))}
          </div>

          <div className="sidebar-tip">
            💡 Hover over highlighted concepts in the explanations to view inline Wikipedia-grounded definitions instantly.
          </div>
        </div>

        <div className="chat-main">
          <div className="chat-header">
            <div className="chat-header-icon">🎓</div>
            <div style={{ flex: 1 }}>
              <div className="chat-header-title">Professor Agent</div>
              <div className="chat-header-sub">Adaptive Chat Tutor • Inline definitions • Wolfram computational engine</div>
            </div>
            {paperId && (
              <button 
                className={`btn btn-ghost sources-toggle-btn ${showSourcesPanel ? 'active' : ''}`}
                onClick={() => setShowSourcesPanel(prev => !prev)}
                title="Toggle Reference Sources Panel"
                style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                📚 Sources ({citations.length})
              </button>
            )}
          </div>

          <div className="chat-messages">
            {messages.map((m, i) => (
              <ChatBubble 
                key={i} 
                role={m.role} 
                content={m.content} 
                signal={m.signal} 
                concepts={paperConcepts}
                onHoverConcept={handleHoverConcept}
                verifiedByWolfram={m.verifiedByWolfram}
                onCiteClick={scrollToCitation}
              />
            ))}
            {loading && (
              <div className="chat-bubble-row assistant fade-in">
                <div className="chat-avatar">🎓</div>
                <div className="chat-bubble thinking">
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="chat-input-area">
            <div className="chat-mode-bar" style={{ display: 'flex', alignItems: 'center', gap: '8px', paddingBottom: '8px', paddingLeft: '8px' }}>
              <div 
                className="mode-toggle-group"
                style={{
                  display: 'flex', alignItems: 'center',
                  background: 'var(--bg-glass-strong)', 
                  border: '1px solid var(--glass-border)',
                  borderRadius: '20px', padding: '4px', gap: '4px',
                }}
              >
                <button 
                  type="button"
                  className={`mode-toggle-pill ${!deepStudyMode ? 'active' : ''}`}
                  onClick={() => setDeepStudyMode(false)}
                  style={{
                    background: !deepStudyMode ? 'var(--bg-glass-strong)' : 'transparent',
                    color: !deepStudyMode ? 'white' : 'var(--text-secondary)',
                    border: 'none', padding: '4px 12px', borderRadius: '16px', fontSize: '12px', fontWeight: '600',
                    cursor: 'pointer', transition: 'all 0.2s', boxShadow: !deepStudyMode ? 'var(--shadow-sm)' : 'none'
                  }}
                  title="Fast LLM responses (Standard Mode)"
                >
                  ⚡ Lite
                </button>
                <button 
                  type="button"
                  className={`mode-toggle-pill ${deepStudyMode ? 'active' : ''}`}
                  onClick={() => setDeepStudyMode(true)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '4px',
                    background: deepStudyMode ? 'var(--indigo-600)' : 'transparent',
                    color: deepStudyMode ? 'white' : 'var(--text-secondary)',
                    border: 'none', padding: '4px 12px', borderRadius: '16px', fontSize: '12px', fontWeight: '600',
                    cursor: 'pointer', transition: 'all 0.2s', boxShadow: deepStudyMode ? 'var(--shadow-sm)' : 'none'
                  }}
                  title="Toggle Wolfram Alpha math engine for rigorous step-by-step mathematical breakdowns"
                >
                  <span style={{ fontSize: '14px' }}>∑</span> Deep
                </button>
              </div>
            </div>
            <div className="chat-input-wrapper">
              <textarea
                ref={inputRef}
                className="chat-input"
                placeholder="Ask the professor anything about the paper…"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={1}
                disabled={loading}
              />
              <button
                className="chat-send-btn btn btn-primary"
                onClick={sendMessage}
                disabled={!input.trim() || loading}
              >
                {loading ? <span className="spinner" /> : '➤'}
              </button>
            </div>
            <div className="chat-input-hint">Press Enter to send · Shift+Enter for new line</div>
          </div>
        </div>
        
        {/* Sources Panel */}
        {paperId && showSourcesPanel && (
          <div className="chat-sources-panel fade-in">
            <div className="sources-header">
              <h3>Sources & Citations</h3>
              <button className="close-btn" onClick={() => setShowSourcesPanel(false)}>×</button>
            </div>
            <div className="sources-list">
              <div className="sources-count">{citations.length} resource{citations.length !== 1 ? 's' : ''}</div>
              {citations.map((cite) => {
                const isHighlighted = highlightedCitationId === cite.citation_index;
                return (
                  <div 
                    key={cite.citation_index} 
                    id={`citation-card-${cite.citation_index}`}
                    className={`citation-card ${isHighlighted ? 'highlighted' : ''}`}
                  >
                    <div className="citation-header-row">
                      <div className="citation-number">{cite.citation_index}</div>
                      <div className="citation-badge-wrapper">
                        <span className={`source-badge badge-${cite.source_type.toLowerCase()}`}>
                          {cite.source_type === 'PrimarySource' ? 'Primary' : cite.source_type}
                        </span>
                        <span className={`peer-badge ${cite.is_preprint ? 'preprint' : 'peer-reviewed'}`}>
                          {cite.is_preprint ? 'Preprint' : 'Peer-reviewed'}
                        </span>
                      </div>
                    </div>
                    
                    <h4 className="citation-title">
                      {cite.url ? (
                        <a href={cite.url} target="_blank" rel="noreferrer">
                          {cite.title}
                        </a>
                      ) : cite.title}
                    </h4>

                    {cite.authors && cite.authors.length > 0 && (
                      <div className="citation-authors">
                        {cite.authors.join(', ')}
                      </div>
                    )}

                    <div className="citation-meta-row">
                      {cite.venue && <span className="citation-venue">{cite.venue}</span>}
                      {cite.year && <span className="citation-year">({cite.year})</span>}
                    </div>

                    <div className="influence-score-container">
                      <div className="influence-label">
                        <span>Citation Percentile (IS)</span>
                        <strong>{cite.influence_score}%</strong>
                      </div>
                      <div className="influence-bar-track">
                        <div 
                          className="influence-bar-fill"
                          style={{ width: `${cite.influence_score}%` }}
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
              {citations.length === 0 && (
                <div className="empty-sources">
                  No citations recorded yet. Ask a question to enrich context.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

import { useState, useEffect, useCallback, useRef } from 'react';
import { getKnowledgeGraph } from '../api/client';
import './GraphPage.css';

// Simple canvas-based force graph without external dep — lightweight, 0 bundle cost
function ForceGraph({ nodes, containerRef }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !nodes.length) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.offsetWidth;
    const H = canvas.offsetHeight;
    canvas.width = W;
    canvas.height = H;

    // Simple spring-layout simulation (50 iterations, no animation for stability)
    const pts = nodes.map((n, i) => ({
      ...n,
      x: W / 2 + (Math.random() - 0.5) * W * 0.7,
      y: H / 2 + (Math.random() - 0.5) * H * 0.7,
      vx: 0,
      vy: 0,
    }));

    for (let iter = 0; iter < 120; iter++) {
      // Repulsion
      for (let a = 0; a < pts.length; a++) {
        for (let b = a + 1; b < pts.length; b++) {
          const dx = pts[b].x - pts[a].x;
          const dy = pts[b].y - pts[a].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = 2800 / (dist * dist);
          pts[a].vx -= force * dx / dist;
          pts[a].vy -= force * dy / dist;
          pts[b].vx += force * dx / dist;
          pts[b].vy += force * dy / dist;
        }
      }
      // Gravity toward center
      pts.forEach(p => {
        p.vx += (W / 2 - p.x) * 0.005;
        p.vy += (H / 2 - p.y) * 0.005;
        p.x += p.vx * 0.1;
        p.y += p.vy * 0.1;
        p.vx *= 0.85;
        p.vy *= 0.85;
        p.x = Math.max(60, Math.min(W - 60, p.x));
        p.y = Math.max(40, Math.min(H - 40, p.y));
      });
    }

    // Draw
    ctx.clearRect(0, 0, W, H);

    // Nodes
    pts.forEach(p => {
      const conf = p.confidence || 0;
      const r = 8 + conf * 10;
      const color = conf >= 0.6
        ? '#10b981'
        : conf >= 0.4
        ? '#f59e0b'
        : conf > 0
        ? '#6366f1'
        : '#374151';

      // Glow
      if (conf > 0) {
        const grad = ctx.createRadialGradient(p.x, p.y, r, p.x, p.y, r * 2.5);
        grad.addColorStop(0, color + '55');
        grad.addColorStop(1, 'transparent');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * 2.5, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fillStyle = color + 'cc';
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Label
      ctx.fillStyle = '#e2e8f0';
      ctx.font = `500 ${Math.max(10, 11 + conf * 3)}px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText(
        p.display_name.length > 18 ? p.display_name.slice(0, 17) + '…' : p.display_name,
        p.x, p.y + r + 14,
      );
    });
  }, [nodes]);

  return <canvas ref={canvasRef} className="graph-canvas" />;
}

export default function GraphPage() {
  const containerRef = useRef(null);
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');
  const [search, setSearch]   = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const d = await getKnowledgeGraph();
      setData(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Convert the flat concepts map into nodes for the graph
  const allNodes = data
    ? Object.entries(data.concepts).map(([name, confidence]) => ({
        id: name,
        canonical_name: name,
        display_name: name.replace(/_/g, ' '),
        confidence,
      }))
    : [];

  const filtered = search
    ? allNodes.filter(n => n.display_name.toLowerCase().includes(search.toLowerCase()))
    : allNodes;

  const masteredCount  = allNodes.filter(n => n.confidence >= 0.8).length;
  const learnedCount   = allNodes.filter(n => n.confidence >= 0.6 && n.confidence < 0.8).length;
  const inProgressCount = allNodes.filter(n => n.confidence > 0 && n.confidence < 0.6).length;

  return (
    <div className="page-content graph-page">
      <div className="bg-glow" />

      <div className="section-header">
        <div>
          <h1 className="section-title">Knowledge Graph</h1>
          <p className="section-subtitle">Your personal concept confidence map — bigger nodes = more confident</p>
        </div>
        <button className="btn btn-ghost" onClick={load} disabled={loading}>
          {loading ? <span className="spinner" /> : '↻'} Refresh
        </button>
      </div>

      {data && (
        <div className="graph-stats card card-padded fade-in">
          <div className="graph-stat">
            <span className="graph-stat-dot" style={{ background: '#10b981' }} />
            <span className="graph-stat-num">{masteredCount}</span>
            <span className="graph-stat-label">Mastered (≥80%)</span>
          </div>
          <div className="graph-stat">
            <span className="graph-stat-dot" style={{ background: '#f59e0b' }} />
            <span className="graph-stat-num">{learnedCount}</span>
            <span className="graph-stat-label">Learned (60–80%)</span>
          </div>
          <div className="graph-stat">
            <span className="graph-stat-dot" style={{ background: '#6366f1' }} />
            <span className="graph-stat-num">{inProgressCount}</span>
            <span className="graph-stat-label">In Progress (&lt;60%)</span>
          </div>
          <div className="graph-stat">
            <span className="graph-stat-dot" style={{ background: '#374151' }} />
            <span className="graph-stat-num">{allNodes.length - masteredCount - learnedCount - inProgressCount}</span>
            <span className="graph-stat-label">Not started</span>
          </div>
        </div>
      )}

      {allNodes.length > 0 && (
        <div className="graph-canvas-card card fade-in" ref={containerRef}>
          <ForceGraph nodes={allNodes} containerRef={containerRef} />
        </div>
      )}

      {data && (
        <>
          <div className="graph-list-header">
            <div className="section-title" style={{ fontSize: 18 }}>All Concepts</div>
            <input
              className="graph-search"
              placeholder="Search concepts…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          <div className="concept-grid">
            {filtered.map(n => (
              <div key={n.id} className="concept-pill card">
                <div className="concept-pill-name">{n.display_name}</div>
                <div className="confidence-bar">
                  <div className="progress-track" style={{ flex: 1, height: '3px' }}>
                    <div
                      className="progress-fill"
                      style={{
                        width: `${Math.round(n.confidence * 100)}%`,
                        background: n.confidence >= 0.6 ? 'var(--success)' : n.confidence >= 0.4 ? 'var(--warning)' : 'var(--indigo-500)',
                      }}
                    />
                  </div>
                  <span className="confidence-label">{Math.round(n.confidence * 100)}%</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {loading && (
        <div className="empty-state">
          <div className="spinner" style={{ width: 32, height: 32 }} />
        </div>
      )}

      {!loading && allNodes.length === 0 && !error && (
        <div className="empty-state">
          <div className="empty-state-icon">🧠</div>
          <h3>Knowledge graph is empty</h3>
          <p>Upload a paper and interact with the professor to start building your knowledge map.</p>
        </div>
      )}

      {error && (
        <div className="error-banner">
          <span>❌</span> {error}
        </div>
      )}
    </div>
  );
}

import React from 'react';
import { useNavigate } from 'react-router-dom';
import './LandingPage.css';

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="landing-container">
      {/* Hero Section */}
      <header className="hero-section">
        <div className="hero-content">
          <h1>See what a paper assumes you already know</h1>
          <p className="hero-subtitle">
            PaperMind extracts the implicit prerequisites behind every machine learning paper, building a personalized topological roadmap to understanding.
          </p>
          <div className="hero-actions">
            <button className="btn-primary" onClick={() => navigate('/auth')}>
              Upload your own
            </button>
            <button className="btn-secondary" onClick={() => {
              // Simulate loading a pre-cached demo paper
              navigate('/auth');
            }}>
              Try instantly
            </button>
          </div>
        </div>
        <div className="hero-visual">
          {/* A simulated animated graph node cluster could go here */}
          <div className="demo-graph">
            <div className="node n1">Query / Key / Value</div>
            <div className="edge e1"></div>
            <div className="node n2">Scaled Dot-Product</div>
            <div className="edge e2"></div>
            <div className="node n3 active">Multi-Head Attention</div>
          </div>
        </div>
      </header>

      {/* The Gap, Made Explicit */}
      <section className="gap-section">
        <div className="container">
          <h2>The Gap, Made Explicit</h2>
          <div className="comparison-grid">
            <div className="comparison-card raw-rag">
              <h3>Raw RAG Chunk</h3>
              <div className="card-content">
                <p>
                  "We compute attention weights via a softmax over scaled dot products of queries and keys..."
                </p>
                <div className="badge">Leaves you confused</div>
              </div>
            </div>
            <div className="comparison-card papermind">
              <h3>PaperMind Structured Roadmap</h3>
              <div className="card-content">
                <ul className="roadmap-preview">
                  <li><span className="check">✓</span> Softmax Function</li>
                  <li><span className="check">✓</span> Scaled Dot-Product</li>
                  <li className="current"><span className="arrow">→</span> Multi-Head Attention</li>
                </ul>
                <div className="badge success">Builds foundational understanding</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Try a Real Paper */}
      <section className="demo-papers-section">
        <div className="container">
          <h2>Try a Real Paper</h2>
          <p>Explore these pre-processed foundational papers instantly.</p>
          <div className="papers-grid">
            {['Attention Is All You Need', 'ResNet-50', 'GPT-3', 'BERT'].map(paper => (
              <div key={paper} className="paper-card" onClick={() => navigate('/auth')}>
                <div className="paper-title">{paper}</div>
                <div className="paper-cta">Explore Graph →</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="container">
          <p>© 2026 PaperMind. Built for the hackathon.</p>
          <div className="footer-links">
            <a href="https://github.com/rudra/PaperMind" target="_blank" rel="noreferrer">GitHub</a>
            <span className="hackathon-badge">Powered by Cognee & Supabase</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

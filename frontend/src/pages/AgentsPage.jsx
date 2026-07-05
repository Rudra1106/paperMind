import React from 'react';
import './AgentsPage.css';

const AGENT_CATEGORIES = [
  {
    title: 'Literature & Materials',
    count: 3,
    agents: [
      {
        id: 'academic_search',
        name: 'Academic Search',
        description: 'Search and identify relevant academic resources for your research topic.',
        icon: (
          <div className="agent-icon-box" style={{ background: '#eef2ff', color: '#6366f1' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
          </div>
        )
      },
      {
        id: 'chat_with_paper',
        name: 'Chat with Paper',
        description: 'Upload papers to summarize findings, ask questions, and trace supporting evidence.',
        icon: (
          <div className="agent-icon-box" style={{ background: '#e0e7ff', color: '#4f46e5' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
          </div>
        )
      },
      {
        id: 'kb_chat',
        name: 'Knowledge Base Chat',
        description: 'Retrieve information and get grounded answers from your personal knowledge base.',
        icon: (
          <div className="agent-icon-box" style={{ background: '#ede9fe', color: '#8b5cf6' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>
          </div>
        )
      }
    ]
  },
  {
    title: 'Research & Writing',
    count: 2,
    agents: [
      {
        id: 'deep_research',
        name: 'Deep Research',
        description: 'Explore a field in depth and produce a structured research report.',
        icon: (
          <div className="agent-icon-box" style={{ background: '#fae8ff', color: '#d946ef' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"></circle><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon></svg>
          </div>
        )
      },
      {
        id: 'lit_review',
        name: 'Literature Review Writer',
        description: 'Search, outline, and compare relevant literature to generate a structured literature review draft.',
        icon: (
          <div className="agent-icon-box" style={{ background: '#f3e8ff', color: '#a855f7' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
          </div>
        )
      }
    ]
  },
  {
    title: 'Figures & Visuals',
    count: 1,
    agents: [
      {
        id: 'scidraw',
        name: 'SciDraw',
        description: 'Generate publication-ready scientific figures from your ideas and requirements.',
        icon: (
          <div className="agent-icon-box" style={{ background: '#dcfce7', color: '#22c55e' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
          </div>
        )
      }
    ]
  }
];

export default function AgentsPage() {
  return (
    <div className="agents-page">
      <div className="agents-header-section">
        <h1 className="agents-page-title">Agents</h1>
        
        <div className="agents-hero-banner">
          <div className="hero-pill">
            <span className="hero-pill-tag">Literature Review Writer</span>
            <span className="hero-pill-text">Turn a research topic into a structured review dr...</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
          </div>
          <div className="hero-dots">
            <span className="dot active"></span>
            <span className="dot"></span>
            <span className="dot"></span>
          </div>
        </div>
      </div>

      <div className="agents-list-container">
        {AGENT_CATEGORIES.map(category => (
          <div key={category.title} className="agent-category">
            <h3 className="category-title">
              {category.title} <span className="category-count">{category.count}</span>
            </h3>
            
            <div className="agents-grid">
              {category.agents.map(agent => (
                <div 
                  key={agent.id} 
                  className="agent-card"
                  onClick={() => alert(`Opening ${agent.name}... (Agent UI Coming Soon - This is a mock)`)}
                >
                  {agent.icon}
                  <div className="agent-details">
                    <h4>{agent.name}</h4>
                    <p>{agent.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

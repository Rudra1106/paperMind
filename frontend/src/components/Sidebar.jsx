import React, { useState } from 'react';
import { NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { supabase } from '../pages/AuthPage';
import './Sidebar.css';

const SIDEBAR_SECTIONS = [
  {
    title: 'Discover',
    to: '/',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
    )
  },
  {
    title: 'Learning Roadmap',
    to: '/roadmap',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
      </svg>
    )
  },
  {
    title: 'Agents',
    to: '/agents',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect>
        <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path>
      </svg>
    ),
    subItems: [
      { label: 'Literature Review', to: '/agents/lit-review', icon: '📚' },
      { label: 'Chat with Paper', to: '/chat', icon: '💬' },
      { label: 'More', to: '/agents', icon: '✨' },
    ]
  },
  {
    title: 'History',
    to: '/history',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="10"></circle>
        <polyline points="12 6 12 12 16 14"></polyline>
      </svg>
    )
  }
];

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const paperId = searchParams.get('paper_id');
  const [agentsOpen, setAgentsOpen] = useState(true);

  const handleLogout = async () => {
    await supabase.auth.signOut();
    navigate('/landing');
  };

  const getLinkWithPaperId = (path) => {
    if (!paperId || path === '/' || path === '/history') return path;
    return `${path}?paper_id=${paperId}`;
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-brand">
          <div className="brand-logo">PM</div>
          <span className="brand-name">Paper Mind</span>
        </div>
        <button className="new-chat-btn" onClick={() => navigate('/')}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          New Chat
        </button>
      </div>

      <nav className="sidebar-nav">
        {SIDEBAR_SECTIONS.map((section) => {
          const isActive = location.pathname === section.to;
          
          if (section.subItems) {
            return (
              <div key={section.title} className="sidebar-group">
                <div 
                  className={`sidebar-item ${location.pathname.startsWith('/agents') ? 'active-group' : ''}`}
                  onClick={() => setAgentsOpen(!agentsOpen)}
                >
                  <div className="sidebar-item-content">
                    {section.icon}
                    <span>{section.title}</span>
                  </div>
                  <svg 
                    width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                    style={{ transform: agentsOpen ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}
                  >
                    <polyline points="6 9 12 15 18 9"></polyline>
                  </svg>
                </div>
                {agentsOpen && (
                  <div className="sidebar-subitems">
                    {section.subItems.map(sub => (
                      <NavLink 
                        key={sub.label} 
                        to={getLinkWithPaperId(sub.to)}
                        className={({isActive}) => `sidebar-subitem ${isActive ? 'active' : ''}`}
                      >
                        <span className="subitem-icon">{sub.icon}</span>
                        {sub.label}
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            );
          }

          return (
            <NavLink 
              key={section.title} 
              to={getLinkWithPaperId(section.to)}
              className={({isActive}) => `sidebar-item ${isActive ? 'active' : ''}`}
            >
              <div className="sidebar-item-content">
                {section.icon}
                <span>{section.title}</span>
              </div>
            </NavLink>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <NavLink to="/tools" className="sidebar-footer-item">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
            <polyline points="2 17 12 22 22 17"></polyline>
            <polyline points="2 12 12 17 22 12"></polyline>
          </svg>
          More Tools
        </NavLink>
        <div className="sidebar-footer-item">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="2" y1="12" x2="22" y2="12"></line>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
          </svg>
          English (EN)
        </div>
        <button className="logout-btn" onClick={handleLogout}>Log out</button>
      </div>
    </div>
  );
}

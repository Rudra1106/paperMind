import { NavLink } from 'react-router-dom';
import './Navbar.css';

const NAV_ITEMS = [
  { to: '/',       icon: '⬆️',  label: 'Upload' },
  { to: '/roadmap', icon: '🗺️', label: 'Roadmap' },
  { to: '/chat',   icon: '💬',  label: 'Professor' },
  { to: '/graph',  icon: '🧠',  label: 'Knowledge' },
];

export default function Navbar() {
  return (
    <nav className="navbar">
      <NavLink to="/" className="navbar-brand">
        <span className="navbar-brand-icon">📄</span>
        <span>PaperMind</span>
      </NavLink>

      <div className="navbar-nav">
        {NAV_ITEMS.map(({ to, icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            <span className="nav-link-icon">{icon}</span>
            <span>{label}</span>
          </NavLink>
        ))}
      </div>

      <div className="navbar-status">
        <span className="status-dot" />
        API Connected
      </div>
    </nav>
  );
}

import React, { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import UploadPage from './pages/DiscoverPage'; // Renamed UploadPage to DiscoverPage file but component might still be named DiscoverPage. Let's fix that too.
import AgentsPage from './pages/AgentsPage';
import RoadmapPage from './pages/RoadmapPage';
import TopicPage from './pages/TopicPage';
import ChatPage from './pages/ChatPage';
import GraphPage from './pages/GraphPage';
import LandingPage from './pages/LandingPage';
import AuthPage from './pages/AuthPage';
import { supabase } from './pages/AuthPage';
import './index.css';

export default function App() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
    });

    return () => subscription.unsubscribe();
  }, []);

  if (loading) {
    return <div className="loading-state">Loading PaperMind...</div>;
  }

  return (
    <BrowserRouter>
      <div className="app-layout" style={{ flexDirection: 'row', height: '100vh', overflow: 'hidden' }}>
        {session && <Sidebar />}
        
        <div className="app-body" style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
          <div className="app-content" style={{ flex: 1, overflowY: 'auto' }}>
            <Routes>
              <Route path="/landing" element={!session ? <LandingPage /> : <Navigate to="/" />} />
              <Route path="/auth" element={!session ? <AuthPage /> : <Navigate to="/" />} />
              
              <Route path="/" element={session ? <UploadPage /> : <Navigate to="/landing" />} />
              <Route path="/agents" element={session ? <AgentsPage /> : <Navigate to="/landing" />} />
              <Route path="/roadmap" element={session ? <RoadmapPage /> : <Navigate to="/landing" />} />
              <Route path="/topic" element={session ? <TopicPage /> : <Navigate to="/landing" />} />
              <Route path="/chat" element={session ? <ChatPage /> : <Navigate to="/landing" />} />
              <Route path="/graph" element={session ? <GraphPage /> : <Navigate to="/landing" />} />
            </Routes>
          </div>
        </div>
      </div>
    </BrowserRouter>
  );
}

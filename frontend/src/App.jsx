import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import UploadPage from './pages/UploadPage';
import RoadmapPage from './pages/RoadmapPage';
import ChatPage from './pages/ChatPage';
import GraphPage from './pages/GraphPage';
import './index.css';

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <Navbar />
        <Routes>
          <Route path="/"        element={<UploadPage />} />
          <Route path="/roadmap" element={<RoadmapPage />} />
          <Route path="/chat"    element={<ChatPage />} />
          <Route path="/graph"   element={<GraphPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

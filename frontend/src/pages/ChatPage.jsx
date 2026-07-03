import { useState, useRef, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { sendChatMessage } from '../api/client';
import './ChatPage.css';

function ChatBubble({ role, content, signal }) {
  const isUser = role === 'user';
  return (
    <div className={`chat-bubble-row ${isUser ? 'user' : 'assistant'} fade-in`}>
      <div className="chat-avatar">{isUser ? '👤' : '🎓'}</div>
      <div className="chat-bubble">
        <div className="chat-content">{content}</div>
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
  const [params] = useSearchParams();
  const paperId  = params.get('paper_id') || '';

  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: "Hello! I'm your Professor. I know exactly what concepts this paper introduces and what prerequisites you need. Ask me anything — about the paper, specific concepts, or why something works the way it does.",
    },
  ]);
  const [input, setInput]       = useState('');
  const [loading, setLoading]   = useState(false);
  const [sessionId]             = useState(() => `session_${Date.now()}`);
  const [lastSignal, setSignal] = useState(null);

  const bottomRef = useRef(null);
  const inputRef  = useRef(null);

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
        sessionId,
        message: text,
      });

      setMessages(prev => [...prev, {
        role: 'assistant',
        content: result.response,
        signal: result.confidence_signal,
      }]);

      if (result.confidence_signal) {
        setSignal(result.confidence_signal);
      }
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

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const STARTER_QUESTIONS = [
    "What are the key prerequisites for this paper?",
    "Explain multi-head attention in simple terms",
    "What makes this architecture novel?",
    "What should I study first?",
  ];

  return (
    <div className="chat-page">
      <div className="chat-sidebar">
        <div className="sidebar-header">
          <div className="sidebar-title">Session</div>
          {paperId && (
            <div className="sidebar-paper-id">
              <span>Paper: </span>
              <code>{paperId.slice(0, 8)}…</code>
            </div>
          )}
        </div>

        {lastSignal && (
          <div className={`sidebar-signal signal-${lastSignal.signal_type}`}>
            <div className="signal-badge">
              {lastSignal.signal_type === 'understood' ? '✅' : '❓'} {lastSignal.signal_type}
            </div>
            <div className="signal-concept">{lastSignal.concept}</div>
            <div className="signal-quote">"{lastSignal.detected_from}"</div>
          </div>
        )}

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
          💡 The professor adapts explanations to what you already know. Say "I'm confused about X" or "I already know Y" to get better explanations.
        </div>
      </div>

      <div className="chat-main">
        <div className="chat-header">
          <div className="chat-header-icon">🎓</div>
          <div>
            <div className="chat-header-title">Professor Agent</div>
            <div className="chat-header-sub">Powered by Cognee · Knowledge Graph · OpenRouter</div>
          </div>
        </div>

        <div className="chat-messages">
          {messages.map((m, i) => (
            <ChatBubble key={i} role={m.role} content={m.content} signal={m.signal} />
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
    </div>
  );
}

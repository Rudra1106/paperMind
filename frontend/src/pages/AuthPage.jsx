import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { createClient } from '@supabase/supabase-js';
import './AuthPage.css';

// Initialize Supabase client
// Use publishable key (sb_publishable_...) if available, else fallback to legacy anon key
const supabaseUrl = 
  import.meta.env.VITE_SUPABASE_URL || 
  import.meta.env.SUPABASE_URL || 
  'https://placeholder.supabase.co';
const supabasePublishableKey =
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ||
  import.meta.env.SUPABASE_PUBLISHABLE_KEY ||
  import.meta.env.SUPABASE_ANON_KEY ||
  import.meta.env.VITE_SUPABASE_ANON_KEY ||
  'placeholder';

export const supabase = createClient(supabaseUrl, supabasePublishableKey);

export default function AuthPage() {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    // Log configuration status on mount for debugging
    console.log('[AuthPage] Supabase URL configured:', supabaseUrl !== 'https://placeholder.supabase.co');
    console.log('[AuthPage] Supabase Key configured:', supabasePublishableKey !== 'placeholder');
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    
    // Proactively check if Supabase URL is a placeholder
    if (supabaseUrl === 'https://placeholder.supabase.co' || supabasePublishableKey === 'placeholder') {
      const msg = 'Supabase environment variables are missing. Please check your .env file.';
      console.error('[AuthPage]', msg);
      setError(msg);
      setLoading(false);
      return;
    }
    
    try {
      if (isLogin) {
        const { error } = await supabase.auth.signInWithPassword({
          email,
          password
        });
        if (error) throw error;
        navigate('/');
      } else {
        const { error } = await supabase.auth.signUp({
          email,
          password
        });
        if (error) throw error;
        // In local dev, email confirmation is often disabled, so login might succeed right away
        alert('Check your email for the confirmation link or try logging in.');
        setIsLogin(true);
      }
    } catch (err) {
      console.error('[AuthPage] Auth error:', err);
      // Improve "Load failed" or "Failed to fetch" messaging
      if (err.message === 'Failed to fetch' || err.message === 'Load failed') {
        setError('Network error: Could not connect to the authentication server. Please check your internet connection or backend configuration.');
      } else {
        setError(err.message || 'An unexpected error occurred during authentication.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>{isLogin ? 'Welcome back' : 'Create an account'}</h2>
        <p className="auth-subtitle">
          {isLogin ? 'Sign in to access your knowledge graph.' : 'Join PaperMind to map your knowledge.'}
        </p>
        
        {error && <div className="auth-error">{error}</div>}
        
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Email</label>
            <input 
              type="email" 
              value={email} 
              onChange={(e) => setEmail(e.target.value)} 
              required 
            />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input 
              type="password" 
              value={password} 
              onChange={(e) => setPassword(e.target.value)} 
              required 
            />
          </div>
          <button type="submit" disabled={loading}>
            {loading ? 'Please wait...' : (isLogin ? 'Sign In' : 'Sign Up')}
          </button>
        </form>
        
        <div className="auth-toggle">
          {isLogin ? "Don't have an account? " : "Already have an account? "}
          <button type="button" onClick={() => setIsLogin(!isLogin)} className="toggle-btn">
            {isLogin ? 'Sign up' : 'Sign in'}
          </button>
        </div>
      </div>
    </div>
  );
}

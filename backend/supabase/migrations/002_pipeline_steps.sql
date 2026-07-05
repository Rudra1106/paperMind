-- -*- coding: utf-8 -*-
-- Supabase migration file for PaperMind v2 DAG pipeline, sessions, topics, and external cache.

-- Pipeline Steps
CREATE TABLE IF NOT EXISTS pipeline_steps (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  paper_id    TEXT NOT NULL, -- references papers(id) but since papers(id) is created later in write_graph, we don't strictly require FK here or we defer it. Let's make it a loose string link to keep pipeline step generation flexible before papers are saved.
  step_name   TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending', -- pending | running | done | failed
  result      JSONB,
  error       TEXT,
  started_at  TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  created_at  TIMESTAMPTZ DEFAULT NOW(),xq
  UNIQUE (paper_id, step_name)
);

-- Sessions (ChatGPT-like sidebar history)
CREATE TABLE IF NOT EXISTS sessions (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  paper_id   TEXT, -- loose reference to papers
  topic_id   UUID, -- loose reference to topics
  title      TEXT,
  turns      JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Topics (Multi-paper groups)
CREATE TABLE IF NOT EXISTS topics (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  title         TEXT NOT NULL,
  seed_query    TEXT,
  seed_paper_id TEXT,
  paper_ids     TEXT[] NOT NULL DEFAULT '{}',
  status        TEXT DEFAULT 'building', -- building | done | failed
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- External Cache (Shared cache for external APIs - Wikipedia, Semantic Scholar, Wolfram)
CREATE TABLE IF NOT EXISTS external_cache (
  cache_key   TEXT PRIMARY KEY,
  source      TEXT NOT NULL, -- 'wikipedia' | 'semantic_scholar' | 'wolfram'
  payload     JSONB NOT NULL,
  fetched_at  TIMESTAMPTZ DEFAULT NOW(),
  expires_at  TIMESTAMPTZ
);

-- Enable RLS
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE external_cache ENABLE ROW LEVEL SECURITY;

-- RLS Policies
CREATE POLICY "users own sessions" ON sessions FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "users own topics" ON topics FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "pipeline_steps readable" ON pipeline_steps FOR SELECT TO authenticated USING (true);
CREATE POLICY "pipeline_steps insertable" ON pipeline_steps FOR ALL TO authenticated USING (true);
CREATE POLICY "external_cache readable" ON external_cache FOR SELECT TO authenticated USING (true);
CREATE POLICY "external_cache insertable" ON external_cache FOR ALL TO authenticated USING (true);

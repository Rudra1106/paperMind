-- Jobs table (replaces in-memory dict)
CREATE TABLE jobs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  status      TEXT NOT NULL DEFAULT 'processing',
  stage       TEXT NOT NULL DEFAULT 'queued',
  paper_id    TEXT,
  error       TEXT,
  pdf_hash    TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Papers table (replaces JSONCache concepts_cache.json)
CREATE TABLE papers (
  id          TEXT PRIMARY KEY,          -- our uuid paper_id
  pdf_hash    TEXT UNIQUE NOT NULL,      -- MD5 of bytes, dedup key
  title       TEXT,
  filename    TEXT,
  storage_path TEXT,                     -- Supabase Storage path
  concepts    JSONB NOT NULL DEFAULT '[]',
  edges       JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Confidence scores (replaces confidence_index.json + Cognee per-concept datasets)
CREATE TABLE concept_confidence (
  user_id         UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  canonical_name  TEXT NOT NULL,
  display_name    TEXT,
  confidence      FLOAT NOT NULL DEFAULT 0.0,
  last_source     TEXT DEFAULT 'manual',
  updated_at      TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (user_id, canonical_name)
);

-- RLS policies
ALTER TABLE jobs               ENABLE ROW LEVEL SECURITY;
ALTER TABLE concept_confidence ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users own jobs"       ON jobs               FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "users own confidence" ON concept_confidence FOR ALL USING (auth.uid() = user_id);

-- papers are shared (same paper, multiple users share one graph)
ALTER TABLE papers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "papers readable by authenticated" ON papers FOR SELECT TO authenticated USING (true);
CREATE POLICY "papers insertable by authenticated" ON papers FOR INSERT TO authenticated WITH CHECK (true);

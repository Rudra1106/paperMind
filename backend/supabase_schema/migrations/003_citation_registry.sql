-- Migration file to create citation registry table and enable row level security.

CREATE TABLE IF NOT EXISTS citations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  paper_id        TEXT NOT NULL,
  session_id      UUID,
  citation_index  INTEGER NOT NULL,
  source_type     TEXT NOT NULL, -- 'Wikipedia', 'SemanticScholar', 'OpenAlex', 'PrimarySource'
  title           TEXT NOT NULL,
  authors         TEXT[] DEFAULT '{}',
  year            INTEGER,
  venue           TEXT,
  url             TEXT,
  is_preprint     BOOLEAN DEFAULT FALSE,
  influence_score FLOAT,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (paper_id, session_id, citation_index)
);

-- Enable RLS
ALTER TABLE citations ENABLE ROW LEVEL SECURITY;

-- RLS Policies
CREATE POLICY "citations readable by authenticated" ON citations FOR SELECT TO authenticated USING (true);
CREATE POLICY "citations insertable by authenticated" ON citations FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "citations updateable by authenticated" ON citations FOR ALL TO authenticated USING (true);

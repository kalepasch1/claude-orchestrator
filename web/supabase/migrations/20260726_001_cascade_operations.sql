-- Phase 6: Cascade Operations table for Development Terminal
CREATE TABLE IF NOT EXISTS cascade_operations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'paused', 'completed', 'failed')),
  completed_steps INTEGER NOT NULL DEFAULT 0,
  total_steps INTEGER NOT NULL DEFAULT 0,
  active_agents INTEGER NOT NULL DEFAULT 0,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cascade_operations_status ON cascade_operations(status);
CREATE INDEX IF NOT EXISTS idx_cascade_operations_created ON cascade_operations(created_at DESC);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_cascade_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cascade_operations_updated ON cascade_operations;
CREATE TRIGGER cascade_operations_updated
  BEFORE UPDATE ON cascade_operations
  FOR EACH ROW EXECUTE FUNCTION update_cascade_timestamp();

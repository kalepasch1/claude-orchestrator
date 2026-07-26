-- Phase 6: Fleet Agents table for Development Terminal
CREATE TABLE IF NOT EXISTS fleet_agents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'idle' CHECK (status IN ('active', 'idle', 'error', 'stopping')),
  current_task TEXT DEFAULT '',
  cpu_pct NUMERIC(5,2) DEFAULT 0,
  mem_mb INTEGER DEFAULT 0,
  last_heartbeat TIMESTAMPTZ DEFAULT now(),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fleet_agents_status ON fleet_agents(status);

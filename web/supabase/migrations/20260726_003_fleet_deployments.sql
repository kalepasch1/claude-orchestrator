-- Phase 6: Fleet Deployments table for Development Terminal
CREATE TABLE IF NOT EXISTS fleet_deployments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project TEXT NOT NULL,
  version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'deploying', 'live', 'failed', 'rolled_back')),
  commit_hash TEXT,
  triggered_by TEXT DEFAULT 'system',
  started_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ,
  metadata JSONB DEFAULT '{}',
  deployed_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fleet_deployments_project ON fleet_deployments(project);
CREATE INDEX IF NOT EXISTS idx_fleet_deployments_status ON fleet_deployments(status);
CREATE INDEX IF NOT EXISTS idx_fleet_deployments_deployed ON fleet_deployments(deployed_at DESC);

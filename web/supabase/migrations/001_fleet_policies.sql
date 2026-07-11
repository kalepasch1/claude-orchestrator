-- Fleet policies for auto-resolution engine
CREATE TABLE IF NOT EXISTS fleet_policies (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  product TEXT NOT NULL DEFAULT '*',
  domain TEXT NOT NULL,
  trigger JSONB NOT NULL DEFAULT '{}',
  conditions JSONB NOT NULL DEFAULT '[]',
  actions JSONB NOT NULL DEFAULT '[]',
  enabled BOOLEAN NOT NULL DEFAULT true,
  auto_execute BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_matched_at TIMESTAMPTZ,
  match_count INTEGER NOT NULL DEFAULT 0,
  success_count INTEGER NOT NULL DEFAULT 0
);

-- Index for fast policy lookups
CREATE INDEX IF NOT EXISTS idx_fleet_policies_product_domain ON fleet_policies(product, domain) WHERE enabled = true;

-- RPC for atomic match counting (used by policyEngine.ts)
CREATE OR REPLACE FUNCTION increment_policy_match(policy_id TEXT, was_success BOOLEAN)
RETURNS VOID AS $$
BEGIN
  UPDATE fleet_policies
  SET match_count = match_count + 1,
      success_count = success_count + CASE WHEN was_success THEN 1 ELSE 0 END,
      last_matched_at = now()
  WHERE id = policy_id;
END;
$$ LANGUAGE plpgsql;

-- Enable RLS (only service role should access policies)
ALTER TABLE fleet_policies ENABLE ROW LEVEL SECURITY;

-- Service role can do everything
CREATE POLICY "Service role full access" ON fleet_policies
  FOR ALL USING (true) WITH CHECK (true);

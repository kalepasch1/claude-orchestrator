-- 002_madeus_tenancy_embed.sql
--
-- SHARED DB stubs for the multi-tenant Madeus layer, its embeds and the
-- cross-tenant hivemind. Tables + isolation only — no seed data, no views, no
-- business logic. Sibling tasks build on these; this migration is the contract.
--
-- Two decisions are load-bearing and deliberately enforced here rather than
-- left to application code:
--
--   1. ISOLATION IS ROW-LEVEL. Every tenant-scoped table has RLS enabled with
--      no permissive default policy, so a query that forgets its tenant scope
--      returns NOTHING instead of everything. An app-side filter is one
--      forgotten code path away from a cross-org leak.
--
--   2. THE HIVEMIND TABLE HAS NO TENANT COLUMN. It cannot: an entry traceable
--      to the org that produced it is a leak, not a learning. Anonymisation
--      happens at the source (see HivemindAnonymiser in
--      web/types/madeus-embed.ts) and the schema makes re-identification
--      impossible by simply not carrying the key.
--
-- Idempotent throughout (IF NOT EXISTS), per repo convention.

-- ── Tenancy ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS madeus_tenants (
  tenant_id     TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  -- 'strict' | 'shared_readonly' — mirrors IsolationMode in the TS contract.
  isolation     TEXT NOT NULL DEFAULT 'strict',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- An org that runs several products/subsidiaries. sibling_readable is opt-in:
-- entities are isolated from each other until the tenant says otherwise.
CREATE TABLE IF NOT EXISTS madeus_entities (
  entity_id        TEXT PRIMARY KEY,
  tenant_id        TEXT NOT NULL REFERENCES madeus_tenants(tenant_id) ON DELETE CASCADE,
  display_name     TEXT NOT NULL,
  sibling_readable BOOLEAN NOT NULL DEFAULT false,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_madeus_entities_tenant ON madeus_entities(tenant_id);

CREATE TABLE IF NOT EXISTS madeus_principals (
  principal_id TEXT NOT NULL,
  tenant_id    TEXT NOT NULL REFERENCES madeus_tenants(tenant_id) ON DELETE CASCADE,
  -- Departments this principal may initiate or steer fleets for.
  departments  TEXT[] NOT NULL DEFAULT '{}',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (principal_id, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_madeus_principals_tenant ON madeus_principals(tenant_id);

-- ── Embeds ──────────────────────────────────────────────────────────────────

-- One row per mounted surface. Exists so a host app cannot silently mount a
-- capability the tenant has not been granted, and so parity is auditable:
-- round 11 requires FULL capability parity, not just the strip.
CREATE TABLE IF NOT EXISTS madeus_embed_grants (
  tenant_id  TEXT NOT NULL REFERENCES madeus_tenants(tenant_id) ON DELETE CASCADE,
  host_app   TEXT NOT NULL,
  surface    TEXT NOT NULL,
  granted    BOOLEAN NOT NULL DEFAULT true,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, host_app, surface)
);

-- ── Sign-offs and steering ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS madeus_signoffs (
  signoff_id   TEXT PRIMARY KEY,
  tenant_id    TEXT NOT NULL REFERENCES madeus_tenants(tenant_id) ON DELETE CASCADE,
  entity_id    TEXT REFERENCES madeus_entities(entity_id) ON DELETE SET NULL,
  department   TEXT NOT NULL,
  subject      TEXT NOT NULL,
  -- 'pending' | 'approved' | 'rejected' | 'expired'
  state        TEXT NOT NULL DEFAULT 'pending',
  requested_by TEXT NOT NULL,
  decided_by   TEXT,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_madeus_signoffs_pending
  ON madeus_signoffs(tenant_id, department) WHERE state = 'pending';

CREATE TABLE IF NOT EXISTS madeus_steering (
  tenant_id  TEXT NOT NULL REFERENCES madeus_tenants(tenant_id) ON DELETE CASCADE,
  department TEXT NOT NULL,
  key        TEXT NOT NULL,
  value      TEXT NOT NULL,
  set_by     TEXT NOT NULL,
  set_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, department, key)
);

-- ── Cross-tenant hivemind ───────────────────────────────────────────────────

-- NOTE THE ABSENCE: no tenant_id, no principal_id, and that is the point.
-- cohort_key is an opaque non-reversible grouping key produced by the
-- anonymiser; it groups similar orgs without naming any.
CREATE TABLE IF NOT EXISTS madeus_hivemind_contributions (
  contribution_id   BIGSERIAL PRIMARY KEY,
  cohort_key        TEXT NOT NULL,
  department        TEXT NOT NULL,
  situation         TEXT NOT NULL,
  resolution        TEXT NOT NULL,
  outcome_score     REAL NOT NULL DEFAULT 0,
  observation_count INTEGER NOT NULL DEFAULT 1,
  contributed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_madeus_hivemind_department
  ON madeus_hivemind_contributions(department, outcome_score DESC);

-- ── Isolation ───────────────────────────────────────────────────────────────
--
-- RLS on, and NO permissive policy shipped here on purpose: an unscoped query
-- returns zero rows until a sibling task adds the policy its surface needs.
-- Failing closed is the correct default for a table that spans organisations.

ALTER TABLE madeus_tenants    ENABLE ROW LEVEL SECURITY;
ALTER TABLE madeus_entities   ENABLE ROW LEVEL SECURITY;
ALTER TABLE madeus_principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE madeus_embed_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE madeus_signoffs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE madeus_steering   ENABLE ROW LEVEL SECURITY;

-- The hivemind table is the ONE table that is legitimately cross-tenant, and
-- it is safe to read precisely because it carries no tenant identity. Reads are
-- open; writes stay closed so contributions can only arrive via the anonymiser.
ALTER TABLE madeus_hivemind_contributions ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'madeus_hivemind_contributions'
      AND policyname = 'hivemind_read_all'
  ) THEN
    CREATE POLICY hivemind_read_all
      ON madeus_hivemind_contributions FOR SELECT USING (true);
  END IF;
END $$;

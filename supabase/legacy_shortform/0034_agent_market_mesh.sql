-- Shared role-aware agent market for Orchestrator, Tomorrow, Apparently, and Smarter.
-- Idempotent by design; service-role runner owns writes, dashboard/API can read through RLS views later.

CREATE TABLE IF NOT EXISTS public.agent_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider text NOT NULL,
  model text NOT NULL,
  role text,
  app text,
  capability integer DEFAULT 0,
  cost_tier text DEFAULT 'unknown',
  trust_tier text DEFAULT 'unknown',
  training_policy text DEFAULT 'unknown',
  confidential_ok boolean DEFAULT false,
  crown_jewel_ok boolean DEFAULT false,
  active boolean DEFAULT true,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_profiles_unique_scope_idx
  ON public.agent_profiles(provider, model, COALESCE(role, '*'), COALESCE(app, '*'));

CREATE TABLE IF NOT EXISTS public.agent_bids (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  app text NOT NULL,
  role text NOT NULL,
  provider text,
  model text,
  score numeric DEFAULT 0,
  sensitivity text DEFAULT 'standard',
  settlement text,
  objective text,
  reason text,
  accepted boolean DEFAULT false,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_bids_app_role_created_idx
  ON public.agent_bids(app, role, created_at DESC);

CREATE TABLE IF NOT EXISTS public.agent_debates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  app text NOT NULL,
  task_slug text,
  role text,
  author_provider text,
  author_model text,
  reviewer_provider text,
  reviewer_model text,
  objection text,
  resolution text,
  tokens_avoided integer DEFAULT 0,
  minutes_avoided numeric DEFAULT 0,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_debates_app_task_idx
  ON public.agent_debates(app, task_slug, created_at DESC);

CREATE TABLE IF NOT EXISTS public.agent_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  app text NOT NULL,
  task_slug text,
  role text NOT NULL,
  provider text,
  model text,
  bid_id uuid REFERENCES public.agent_bids(id) ON DELETE SET NULL,
  status text DEFAULT 'assigned',
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_assignments_app_task_idx
  ON public.agent_assignments(app, task_slug, role);

CREATE TABLE IF NOT EXISTS public.agent_outcomes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  app text NOT NULL,
  task_slug text,
  role text,
  provider text,
  model text,
  settlement text,
  settled_value numeric DEFAULT 0,
  cost_usd numeric DEFAULT 0,
  latency_ms integer DEFAULT 0,
  input_tokens integer DEFAULT 0,
  output_tokens integer DEFAULT 0,
  review_failures integer DEFAULT 0,
  rollback boolean DEFAULT false,
  deployed boolean DEFAULT false,
  accepted boolean DEFAULT false,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_outcomes_app_model_idx
  ON public.agent_outcomes(app, provider, model, created_at DESC);

CREATE TABLE IF NOT EXISTS public.agent_reputation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  app text NOT NULL,
  role text NOT NULL,
  provider text NOT NULL,
  model text NOT NULL,
  samples integer DEFAULT 0,
  accepted_rate numeric DEFAULT 0,
  deployed_rate numeric DEFAULT 0,
  rollback_rate numeric DEFAULT 0,
  avg_cost_usd numeric DEFAULT 0,
  avg_latency_ms numeric DEFAULT 0,
  tokens_per_settled_value numeric DEFAULT 0,
  review_failures_per_accept numeric DEFAULT 0,
  score numeric DEFAULT 0,
  updated_at timestamptz DEFAULT now(),
  UNIQUE(app, role, provider, model)
);

CREATE TABLE IF NOT EXISTS public.agent_penalties (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  app text NOT NULL,
  provider text,
  model text,
  task_slug text,
  penalty_type text NOT NULL,
  severity integer DEFAULT 1,
  reason text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_penalties_model_idx
  ON public.agent_penalties(app, provider, model, created_at DESC);

ALTER TABLE public.agent_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_bids ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_debates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_reputation ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_penalties ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'agent_profiles'
      AND policyname = 'agent_profiles_service_role_all'
  ) THEN
    CREATE POLICY agent_profiles_service_role_all ON public.agent_profiles
      FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'agent_bids'
      AND policyname = 'agent_bids_service_role_all'
  ) THEN
    CREATE POLICY agent_bids_service_role_all ON public.agent_bids
      FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'agent_debates'
      AND policyname = 'agent_debates_service_role_all'
  ) THEN
    CREATE POLICY agent_debates_service_role_all ON public.agent_debates
      FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'agent_assignments'
      AND policyname = 'agent_assignments_service_role_all'
  ) THEN
    CREATE POLICY agent_assignments_service_role_all ON public.agent_assignments
      FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'agent_outcomes'
      AND policyname = 'agent_outcomes_service_role_all'
  ) THEN
    CREATE POLICY agent_outcomes_service_role_all ON public.agent_outcomes
      FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'agent_reputation'
      AND policyname = 'agent_reputation_service_role_all'
  ) THEN
    CREATE POLICY agent_reputation_service_role_all ON public.agent_reputation
      FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'agent_penalties'
      AND policyname = 'agent_penalties_service_role_all'
  ) THEN
    CREATE POLICY agent_penalties_service_role_all ON public.agent_penalties
      FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
  END IF;
END $$;

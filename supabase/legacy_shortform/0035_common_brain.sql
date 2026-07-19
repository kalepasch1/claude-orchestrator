-- Reusable Common Brain recipes/deployments.
-- The Darwin kernel is the runtime contract; these tables make deployments auditable.

CREATE TABLE IF NOT EXISTS public.common_brain_recipes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_key text NOT NULL UNIQUE,
  product text NOT NULL,
  surface text NOT NULL,
  domain text NOT NULL,
  settlement text NOT NULL,
  primitives jsonb NOT NULL DEFAULT '[]'::jsonb,
  stages jsonb NOT NULL DEFAULT '[]'::jsonb,
  cade jsonb NOT NULL DEFAULT '{}'::jsonb,
  guardrails jsonb NOT NULL DEFAULT '[]'::jsonb,
  metrics jsonb NOT NULL DEFAULT '[]'::jsonb,
  receipt_digest text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS common_brain_recipes_product_idx
  ON public.common_brain_recipes(product, surface);

CREATE TABLE IF NOT EXISTS public.common_brain_deployments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_key text NOT NULL,
  product text NOT NULL,
  project_id uuid,
  task_slug text,
  status text DEFAULT 'queued',
  outcome text,
  tokens_avoided integer DEFAULT 0,
  minutes_avoided numeric DEFAULT 0,
  review_failures integer DEFAULT 0,
  rollback boolean DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS common_brain_deployments_product_idx
  ON public.common_brain_deployments(product, status, created_at DESC);

ALTER TABLE public.common_brain_recipes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.common_brain_deployments ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'common_brain_recipes'
      AND policyname = 'common_brain_recipes_service_role_all'
  ) THEN
    CREATE POLICY common_brain_recipes_service_role_all ON public.common_brain_recipes
      FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'common_brain_deployments'
      AND policyname = 'common_brain_deployments_service_role_all'
  ) THEN
    CREATE POLICY common_brain_deployments_service_role_all ON public.common_brain_deployments
      FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
  END IF;
END $$;

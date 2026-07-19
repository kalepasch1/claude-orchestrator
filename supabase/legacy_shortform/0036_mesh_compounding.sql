-- Compounding mesh optimizer fields.

CREATE TABLE IF NOT EXISTS public.merged_diffs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project text,
  slug text,
  kind text,
  prompt text,
  diff text,
  files jsonb,
  words jsonb,
  symbols jsonb,
  tests jsonb,
  frameworks jsonb,
  acceptance text,
  created_at timestamptz DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS merged_diffs_project_slug_unique
  ON public.merged_diffs(project, slug);

ALTER TABLE public.merged_diffs
  ADD COLUMN IF NOT EXISTS acceptance_intent text,
  ADD COLUMN IF NOT EXISTS intent_signature text,
  ADD COLUMN IF NOT EXISTS adapter_template text;

CREATE INDEX IF NOT EXISTS merged_diffs_intent_signature_idx
  ON public.merged_diffs(intent_signature);

CREATE UNIQUE INDEX IF NOT EXISTS common_brain_deployments_task_slug_unique
  ON public.common_brain_deployments(task_slug)
  WHERE task_slug IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.intent_graph_edges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_project text,
  source_slug text,
  target_project text,
  target_slug text,
  intent_signature text,
  similarity numeric,
  adapter_template text,
  outcome text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS intent_graph_edges_signature_idx
  ON public.intent_graph_edges(intent_signature, created_at DESC);

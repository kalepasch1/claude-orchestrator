
CREATE TABLE IF NOT EXISTS public.workspace_drafts (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
  capability_slug text NOT NULL,
  app_id text NOT NULL,
  draft_type text NOT NULL DEFAULT 'terminal',
  content jsonb NOT NULL DEFAULT '{}',
  is_deleted boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id, capability_slug, app_id, draft_type)
);

ALTER TABLE public.workspace_drafts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own drafts" ON public.workspace_drafts
  FOR ALL USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

CREATE INDEX idx_workspace_drafts_lookup ON public.workspace_drafts(user_id, capability_slug, app_id) WHERE NOT is_deleted;
;

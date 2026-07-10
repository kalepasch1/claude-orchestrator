-- 0038_run_logs.sql — per-line log streaming table for real-time web sync.
--
-- Replaces the `tasks.log_tail` snapshot approach with per-line rows so the
-- web dashboard can subscribe to a Supabase realtime channel and receive each
-- log line as the runner emits it instead of waiting for a full poll cycle.
--
-- Slice-1: table + RLS + realtime publication. The runner calls
-- db.append_run_log() to insert rows; older tasks without rows still fall
-- back to log_tail on the web side.

CREATE TABLE IF NOT EXISTS public.run_logs (
  id           bigserial PRIMARY KEY,
  task_id      uuid        NOT NULL,
  task_slug    text        NOT NULL,
  runner_id    text        NOT NULL DEFAULT '',
  level        text        NOT NULL DEFAULT 'info'
                CHECK (level IN ('debug', 'info', 'warn', 'error')),
  message      text        NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS run_logs_task_id_idx  ON public.run_logs (task_id, created_at);
CREATE INDEX IF NOT EXISTS run_logs_created_idx  ON public.run_logs (created_at DESC);

-- RLS: authenticated users can read; service role writes (runner never goes
-- through the anon key, so no insert policy needed for authenticated users).
ALTER TABLE public.run_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "run_logs_select" ON public.run_logs
  FOR SELECT TO authenticated USING (true);

-- Add to the realtime publication so Supabase channels can fan out changes.
ALTER PUBLICATION supabase_realtime ADD TABLE public.run_logs;

SELECT '0038_run_logs OK — run_logs table created with realtime' AS status;

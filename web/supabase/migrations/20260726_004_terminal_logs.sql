-- Phase 6: Terminal Logs table for Development Terminal
CREATE TABLE IF NOT EXISTS terminal_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
  level TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('debug', 'info', 'warn', 'error')),
  source TEXT NOT NULL DEFAULT 'system',
  message TEXT NOT NULL,
  metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_terminal_logs_timestamp ON terminal_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_terminal_logs_level ON terminal_logs(level);

-- Auto-cleanup: keep only last 7 days of logs
CREATE OR REPLACE FUNCTION cleanup_old_terminal_logs()
RETURNS TRIGGER AS $$
BEGIN
  DELETE FROM terminal_logs WHERE timestamp < now() - interval '7 days';
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Run cleanup every 1000 inserts
DROP TRIGGER IF EXISTS terminal_logs_cleanup ON terminal_logs;
CREATE TRIGGER terminal_logs_cleanup
  AFTER INSERT ON terminal_logs
  FOR EACH STATEMENT EXECUTE FUNCTION cleanup_old_terminal_logs();

-- 0037_fleet_pause.sql — add fleet-wide pause / resume control actions.
--
-- Extends the fleet_control action plane (0033) with two soft-pause actions that
-- any machine can issue at another (target = hostname or 'all'):
--   pause   -> the targeted runner stops CLAIMING new work but stays resident
--              (keepalive does NOT respawn it; a hard launchd stop would fight
--              keepalive and would not be remotely resumable).
--   resume  -> lifts the pause; the runner resumes claiming on its next loop.
--
-- Coordination is pure DB: the acting runner records a host-scoped row in the
-- existing `controls` table (scope='host', project=<hostname>), and its own
-- kill_switch.is_paused() honors it — so Mac 1 can pause Mac 2 (and vice-versa)
-- without touching the other machine's terminal, and without a global pause that
-- would halt the whole fleet.
--
-- `controls.scope` is unconstrained text with unique(scope, project), so the new
-- 'host' scope needs no schema change here — only the fleet_control action check
-- has to admit the two new verbs.

alter table fleet_control drop constraint if exists fleet_control_action_check;
alter table fleet_control
  add constraint fleet_control_action_check
  check (action in ('restart', 'git_pull', 'reload_config', 'pause', 'resume'));

select '0037_fleet_pause OK — actions: restart, git_pull, reload_config, pause, resume' as status;

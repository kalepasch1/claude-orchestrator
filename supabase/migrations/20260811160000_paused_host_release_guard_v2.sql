-- 20260811160000_paused_host_release_guard_v2.sql
--
-- Corrects the paused-host release fence WITHOUT rewriting applied migration history.
-- Recovered from ChatGPT/Codex evidence (audit fingerprint e0945946bd0d…): the branch
-- `codex/orchestrator-session-fabric` carried this fix; every other file in that
-- evidence set is already present on master, so this migration is the only item
-- classified RECOVERABLE_VALUE.
--
-- THE BUG IN v1 (20260806220000_paused_host_release_guard.sql)
-- -----------------------------------------------------------
-- v1's DESIGN NOTES promise that a refusal is "RECORDED, not swallowed", and its trigger
-- body does:
--
--     insert into public.runner_alerts (kind, detail, resolved) values (...);
--     perform pg_notify('release_from_paused_host', v_detail);
--     ...
--     raise exception 'paused-host guard: ...';
--
-- Both of those are transactional. The RAISE aborts the transaction, so the runner_alerts
-- row rolls back and the NOTIFY is never delivered (pg_notify only fires on COMMIT). The
-- guard therefore refused the release correctly but left exactly the silence it was
-- written to eliminate — the one failure mode v1's own comments call out as unacceptable.
--
-- THE FIX
-- -------
-- Stop pretending a trigger can write a durable record alongside its own abort. The
-- rejection is recorded by the CALLER, in a separate transaction, which is already
-- implemented: runner/paused_host_guard.py carries ALERT_KIND = 'release_from_paused_host'
-- and record_rejection(), and runner/tests/test_paused_host_scope.py asserts on it. This
-- migration removes the doomed in-trigger write and documents where the durable record
-- actually lives, so the code and the comments stop disagreeing.
--
-- Everything else about v1 is preserved deliberately:
--   * INSERT only — a pass already in flight must still be able to record its outcome.
--   * NULL/empty host passes — refuse what can be proven, never what cannot be attributed.
--   * stale_host_is_paused() remains the single source of truth, shared with the claim
--     guard, so the two guards can never disagree about whether a host is paused.
--
-- Idempotent: `create or replace` + `drop trigger if exists`, and the column add is
-- `if not exists`, so re-running this after v1 is a no-op beyond the function body.

-- Present since v1; repeated so this migration stands alone on a fresh database.
alter table public.releases add column if not exists host text;

create or replace function public.enforce_paused_host_release_guard()
returns trigger
language plpgsql
as $$
declare
  v_paused boolean;
  v_reason text;
  v_detail text;
begin
  -- Unattributable rows pass. We refuse what we can prove, nothing more.
  if NEW.host is null or NEW.host = '' then
    return NEW;
  end if;

  -- Alias-tolerant, latest-decision-wins lookup shared with trg_stale_host_claim_guard.
  select p.paused, p.reason into v_paused, v_reason
  from public.stale_host_is_paused(NEW.host) p;

  if coalesce(v_paused, false) is not true then
    return NEW;
  end if;

  v_detail := format(
    'host=%s refused releases INSERT project=%s deploy_status=%s to_sha=%s. Reason: %s',
    NEW.host, coalesce(NEW.project, '?'), coalesce(NEW.deploy_status, '?'),
    left(coalesce(NEW.to_sha, ''), 8),
    coalesce(nullif(v_reason, ''), 'no reason recorded'));

  -- NO in-trigger runner_alerts insert and NO pg_notify here: both roll back with the
  -- RAISE below, which is precisely why v1 was silent. The caller records the refusal
  -- durably in its own transaction — see runner/paused_host_guard.record_rejection().
  raise exception
    'paused-host guard: host % is paused and may not record releases. %'
      ' Resume it with kill_switch.resume(scope=''host'', project=''%'') once it is up to date.',
    NEW.host, v_detail, NEW.host
    using errcode = 'check_violation';
end;
$$;

comment on function public.enforce_paused_host_release_guard() is
  'BEFORE INSERT fence for paused release hosts. UPDATEs are unguarded so a pass already '
  'in flight can still record its outcome. The refusal is recorded in runner_alerts by the '
  'CALLER (runner/paused_host_guard.record_rejection) in a separate transaction, because a '
  'trigger-side write rolls back with the exception it accompanies — the v1 bug this fixes.';

drop trigger if exists trg_paused_host_release_guard on public.releases;

create trigger trg_paused_host_release_guard
  before insert on public.releases
  for each row
  when (NEW.host is not null and NEW.host <> '')
  execute function public.enforce_paused_host_release_guard();

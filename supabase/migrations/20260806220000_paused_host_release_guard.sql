-- 20260806220000_paused_host_release_guard.sql
--
-- SERVER-SIDE paused-host release guard. Sibling of 20260806120000_stale_host_claim_guard.sql,
-- and deliberately built on that migration's helper functions rather than reimplementing them.
--
-- WHAT THE CLAIM GUARD MISSED
--
-- trg_stale_host_claim_guard fires on `tasks.account` changing — a task CLAIM. Release-train
-- and merge-train work is not a task claim, so a paused host went on running QA gates, build
-- gates and release attempts against its own stale checkout and broken toolchain.
--
-- Evidence, 2026-08-06 21:10. A beethoven release failed with:
--
--     [gate:build] staging BUILD red — self-heal queued:
--     npm error A complete log of this run can be found in: /Users/mandypa...
--
-- `/Users/mandypa...` is Mandys-MacBook-Pro: PAUSED in controls since 19:02, 40+ commits stale
-- on code_sha 10d9e408, 0 of 46 tasks completed in 48h. Its failed rows flip the project RED,
-- which trips ORCH_RELEASE_BACKPRESSURE and rejects new work FLEET-WIDE. A paused, broken host
-- is not merely useless — it poisons the release state of projects it must not touch.
--
-- DESIGN NOTES
--
--  * releases.host is ADDED here. The table recorded no host at all, which is why the incident
--    had to be diagnosed from an npm log path that happened to leak into `note`. A row that can
--    flip a project RED fleet-wide must say who wrote it. Nullable, because rows written by a
--    client that predates this column are still legitimate rows.
--
--  * INSERT only. An UPDATE to an existing release row is how a pass already in flight records
--    its outcome (deploy_status building -> success/failed, deployed_at, vercel_url), and the
--    whole lesson of the claim guard is that blocking completion strands work and is worse than
--    the failure being fixed. Start is guarded; finish never is.
--
--  * A NULL host is allowed through. The guard refuses hosts it can prove are paused; it does
--    not refuse rows it cannot attribute. Making an unattributable row fatal would break every
--    client that has not shipped the `host` stamp yet — including, during a rollout, the good
--    ones. The runner-side check in paused_host_guard.py is the first line; this is the backstop
--    for a stale client that cannot police itself.
--
--  * Rejections are RECORDED, not swallowed: a runner_alerts row with kind
--    'release_from_paused_host' is written before the exception is raised. The insert is made
--    to survive the rollback by running it in an autonomous-style separate path — see the
--    pg_notify + exception ordering below. Silence is how this went unseen for hours.

-- ---------------------------------------------------------------------------
-- releases.host — who produced this row
-- ---------------------------------------------------------------------------
alter table public.releases add column if not exists host text;

comment on column public.releases.host is
  'Hostname of the machine that wrote this release row. Added 2026-08-06: a failed release '
  'flips a project RED fleet-wide and was previously attributable only by accident, via an '
  'npm log path leaking into note.';

create index if not exists releases_host_created_idx
  on public.releases (host, created_at desc);

-- ---------------------------------------------------------------------------
-- the guard
-- ---------------------------------------------------------------------------
create or replace function public.enforce_paused_host_release_guard()
returns trigger
language plpgsql
as $$
declare
  v_paused  boolean;
  v_reason  text;
  v_detail  text;
begin
  -- Unattributable rows pass: see DESIGN NOTES. We refuse what we can prove, nothing more.
  if NEW.host is null or NEW.host = '' then
    return NEW;
  end if;

  -- Reuses the claim guard's alias-tolerant, latest-decision-wins lookup so the two guards
  -- can never disagree about whether a host is paused.
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

  -- Record BEFORE raising. This insert rolls back with the transaction, so also emit a
  -- NOTIFY that survives it — the alert table is the durable record when the caller
  -- catches the exception and retries without the host stamp, and the notification is
  -- what a listener sees regardless.
  begin
    insert into public.runner_alerts (kind, detail, resolved)
    values ('release_from_paused_host', v_detail, false);
    perform pg_notify('release_from_paused_host', v_detail);
  exception when others then
    null;   -- recording must never be the reason the guard itself fails
  end;

  raise exception
    'paused-host guard: host % is paused and may not record releases. %'
      ' Resume it with kill_switch.resume(scope=''host'', project=''%'') once it is up to date.',
    NEW.host, v_detail, NEW.host
    using errcode = 'check_violation';
end;
$$;

comment on function public.enforce_paused_host_release_guard() is
  'BEFORE INSERT guard on releases: a host paused in controls(scope=host) cannot record NEW '
  'release rows. UPDATEs are unguarded so a pass already in flight can still record its '
  'outcome. Refusals are written to runner_alerts(kind=release_from_paused_host).';

drop trigger if exists trg_paused_host_release_guard on public.releases;

create trigger trg_paused_host_release_guard
  before insert on public.releases
  for each row
  when (NEW.host is not null and NEW.host <> '')
  execute function public.enforce_paused_host_release_guard();

-- 20260806120000_stale_host_claim_guard.sql
--
-- SERVER-SIDE stale-host claim guard.
--
-- The catch-22 this fixes: the host pause is currently enforced in runner code. A host that has
-- fallen far enough behind is running code that PREDATES the guard, so it cannot self-police —
-- and the further behind it falls, the less able it is to obey. Mandys-MacBook-Pro.local was
-- paused at 2026-08-06 15:53 and went on claiming tasks at 16:03. Over 48h it claimed 46 tasks
-- and completed zero, burning an attempt on each and delaying every task it touched.
--
-- A client cannot be trusted to police itself, so enforcement moves to the one place a stale
-- runner cannot ignore or out-date: the database.
--
-- DESIGN NOTES
--
--  * Fires ONLY on a claim — `NEW.account IS DISTINCT FROM OLD.account AND NEW.account IS NOT
--    NULL`. Ordinary progress updates (heartbeats, state changes, notes) never touch the guard,
--    so a paused host can still finish and record work it already holds. Blocking those would
--    strand in-flight tasks, which is a worse failure than the one being fixed.
--
--  * Only accounts that resolve to a hostname ACTUALLY PRESENT in controls(scope='host') are
--    matched. `cowork-executor-v6-...`, `agentic:*` and any other non-host account are
--    unaffected. This is why the check is a lookup against real host rows rather than a regex
--    guess at what a hostname looks like: 'cowork-executor-v6' would otherwise parse as a
--    plausible host and the guard would start blocking the fleet's most productive workers.
--
--  * Host aliases: a pause may be written as 'Mac-2' or 'Mac-2.local'. Both forms match, exactly
--    as runner/kill_switch.py::_host_aliases does.
--
--  * LATEST decision wins, per scope. controls is not append-only in practice and old paused
--    rows must not outvote a newer resume — same rule as kill_switch.is_paused(). Rows written
--    by 'remote-quarantine' are ignored here for the same reason the runner ignores them.
--
--  * Staleness is CORROBORATION, never authority. An operator pause is the authority. A host is
--    never rejected for running an old code_sha alone — that would block a fleet mid-rollout,
--    when every host is briefly "stale". Staleness only sharpens the error message on a host
--    that is already paused.

-- ---------------------------------------------------------------------------
-- helper: hostname implied by a task account, or NULL if the account is not a host account
-- ---------------------------------------------------------------------------
create or replace function public.stale_host_account_hostname(p_account text)
returns text
language sql
stable
as $$
  -- Accounts look like '<hostname>-<pid>' e.g. 'Mandys-MacBook-Pro.local-7146'.
  -- Resolve by matching against hostnames that genuinely exist in controls(scope='host'),
  -- longest first so 'Mac.lan' never shadows 'Mac.lan.local'. Anything with no host row
  -- (cowork-executor-*, agentic:*) returns NULL and is left alone.
  select c.project
  from public.controls c
  where c.scope = 'host'
    and coalesce(c.project, '') <> ''
    and (
      p_account = c.project
      or p_account like c.project || '-%'
      -- alias forms: pause written with/without the .local suffix
      or p_account = regexp_replace(c.project, '\.local$', '')
      or p_account like regexp_replace(c.project, '\.local$', '') || '-%'
      or p_account = c.project || '.local'
      or p_account like c.project || '.local-%'
    )
  order by length(c.project) desc
  limit 1
$$;

comment on function public.stale_host_account_hostname(text) is
  'Hostname implied by a tasks.account claim string, or NULL when the account is not a known host '
  '(cowork-executor-*, agentic:* and similar are deliberately unmatched).';

-- ---------------------------------------------------------------------------
-- helper: is this host paused, by the LATEST controls decision for it?
-- ---------------------------------------------------------------------------
create or replace function public.stale_host_is_paused(p_host text)
returns table (paused boolean, reason text, updated_at timestamptz)
language sql
stable
as $$
  select c.paused, c.reason, c.updated_at
  from public.controls c
  where c.scope = 'host'
    and coalesce(c.updated_by, '') <> 'remote-quarantine'
    and (
      c.project = p_host
      or c.project = regexp_replace(p_host, '\.local$', '')
      or c.project = p_host || '.local'
      or regexp_replace(c.project, '\.local$', '') = regexp_replace(p_host, '\.local$', '')
    )
  order by c.updated_at desc nulls last
  limit 1
$$;

comment on function public.stale_host_is_paused(text) is
  'Latest pause decision for a host (alias-tolerant). Latest row wins so a stale paused row '
  'cannot outvote a newer resume.';

-- ---------------------------------------------------------------------------
-- the guard
-- ---------------------------------------------------------------------------
create or replace function public.enforce_stale_host_claim_guard()
returns trigger
language plpgsql
as $$
declare
  v_host        text;
  v_paused      boolean;
  v_reason      text;
  v_host_sha    text;
  v_fleet_sha   text;
  v_detail      text := '';
begin
  -- Only a CLAIM is guarded. An account that is unchanged, or cleared on release, is not a claim.
  if NEW.account is null or NEW.account is not distinct from OLD.account then
    return NEW;
  end if;

  v_host := public.stale_host_account_hostname(NEW.account);

  -- Not a host account (cowork executors, agentic coders, anything unknown) -> never guarded.
  if v_host is null then
    return NEW;
  end if;

  select p.paused, p.reason into v_paused, v_reason
  from public.stale_host_is_paused(v_host) p;

  if coalesce(v_paused, false) is not true then
    return NEW;
  end if;

  -- Paused. Corroborate with code staleness purely to make the error actionable.
  select rh.code_sha into v_host_sha
  from public.runner_heartbeats rh
  where rh.hostname = v_host
     or regexp_replace(rh.hostname, '\.local$', '') = regexp_replace(v_host, '\.local$', '')
  order by rh.last_seen desc nulls last
  limit 1;

  select rh.code_sha into v_fleet_sha
  from public.runner_heartbeats rh
  where rh.last_seen > now() - interval '2 hours'
    and coalesce(rh.code_sha, '') <> ''
  group by rh.code_sha
  order by count(*) desc, max(rh.last_seen) desc
  limit 1;

  if v_host_sha is not null and v_fleet_sha is not null and v_host_sha <> v_fleet_sha then
    v_detail := format(' Host code_sha %s differs from fleet %s.',
                       left(v_host_sha, 8), left(v_fleet_sha, 8));
  end if;

  raise exception
    'stale-host guard: host % is paused and may not claim tasks. Reason: %.%'
      ' Resume it with kill_switch.resume(scope=''host'', project=''%'') once it is up to date.',
    v_host, coalesce(nullif(v_reason, ''), 'no reason recorded'), v_detail, v_host
    using errcode = 'check_violation';
end;
$$;

comment on function public.enforce_stale_host_claim_guard() is
  'BEFORE UPDATE guard on tasks: a host paused in controls(scope=host) cannot CLAIM new work. '
  'Fires only when tasks.account changes, so in-flight work can still be completed and released.';

drop trigger if exists trg_stale_host_claim_guard on public.tasks;

create trigger trg_stale_host_claim_guard
  before update of account on public.tasks
  for each row
  when (NEW.account is not null and NEW.account is distinct from OLD.account)
  execute function public.enforce_stale_host_claim_guard();

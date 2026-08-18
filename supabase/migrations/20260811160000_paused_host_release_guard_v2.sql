-- Correct the paused-host release fence without rewriting applied migration history.
-- Trigger-side writes and NOTIFY roll back with the rejected release, so the
-- current runner records the durable alert in a separate transaction.

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
  if NEW.host is null or NEW.host = '' then
    return NEW;
  end if;

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

  raise exception
    'paused-host guard: host % is paused and may not record releases. %'
      ' Resume it with kill_switch.resume(scope=''host'', project=''%'') once it is up to date.',
    NEW.host, v_detail, NEW.host
    using errcode = 'check_violation';
end;
$$;

comment on function public.enforce_paused_host_release_guard() is
  'BEFORE INSERT fence for paused release hosts. The caller records the refusal in '
  'runner_alerts in a separate transaction because trigger-side writes roll back.';

drop trigger if exists trg_paused_host_release_guard on public.releases;
create trigger trg_paused_host_release_guard
  before insert on public.releases
  for each row
  when (NEW.host is not null and NEW.host <> '')
  execute function public.enforce_paused_host_release_guard();

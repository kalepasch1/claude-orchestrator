-- External dead-man's-switch: runs in Supabase (pg_cron), independent of the Mac runner, so runner
-- downtime is always detected + alertable even when the runner itself is dead.
create extension if not exists pg_cron;

create table if not exists runner_alerts (
  id bigint generated always as identity primary key,
  kind text not null, detail text, resolved boolean not null default false,
  created_at timestamptz not null default now()
);
alter table runner_alerts enable row level security;
drop policy if exists runner_alerts_sel on runner_alerts;
create policy runner_alerts_sel on runner_alerts for select to authenticated using (true);

-- optional webhook (Slack/etc.) for push alerts; set value to your webhook URL to enable pg_net POSTs
create table if not exists growth_settings (key text primary key, value text);
insert into growth_settings(key,value) values ('runner_alert_webhook','') on conflict do nothing;

create or replace function check_runner_heartbeat(p_stale_secs int default 300)
returns void language plpgsql security definer set search_path=public as $$
declare secs numeric; hook text;
begin
  select extract(epoch from (now()-max(last_seen))) into secs from runner_heartbeats;
  if secs is null or secs > p_stale_secs then
    -- dedupe: only alert if none in the last 15 min
    if not exists (select 1 from runner_alerts where kind='runner_down' and created_at > now()-interval '15 min') then
      insert into runner_alerts(kind, detail)
      values ('runner_down', format('No runner heartbeat for %s seconds (threshold %s).', round(coalesce(secs,-1)), p_stale_secs));
      select value into hook from growth_settings where key='runner_alert_webhook';
      if hook is not null and hook <> '' then
        perform net.http_post(hook, jsonb_build_object('text',
          format(':rotating_light: Orchestrator runner DOWN — no heartbeat for %s s. Restart it (launchd should auto-respawn).', round(coalesce(secs,-1)))));
      end if;
    end if;
  end if;
end $$;

-- run every 5 minutes, always-on in the DB
select cron.schedule('runner-heartbeat-check', '*/5 * * * *', $$select check_runner_heartbeat();$$);;

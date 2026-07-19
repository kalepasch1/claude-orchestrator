-- Cue the social capability into the orchestration control plane so the autonomous system
-- recognizes + governs it (independent of the email 'global' switch), and gate the workers on it.

-- Kill switch for the whole social capability (independent of the email global switch).
create or replace function public.social_enabled()
returns boolean language sql stable as $$
  select coalesce((select mode from public.growth_autonomy_switch where scope='social' and key='') <> 'off', true);
$$;

-- Gate the API worker pull on the social switch.
create or replace function public.social_due_now(p_app text default null, p_limit int default 25)
returns jsonb language plpgsql as $$
declare posts jsonb; acts jsonb;
begin
  if not public.social_enabled() then return jsonb_build_object('posts','[]'::jsonb,'actions','[]'::jsonb,'disabled',true); end if;
  select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) into posts from (
    select id, app, account_id, platform, kind, title, body, scheduled_at
    from public.growth_social_post p
    where autonomy='auto' and status in ('scheduled','queued')
      and (scheduled_at is null or scheduled_at <= now())
      and public.effective_exec_method(p.account_id, p.exec_method) <> 'chrome'
      and (p_app is null or app=p_app)
    order by scheduled_at nulls first limit p_limit) x;
  select coalesce(jsonb_agg(to_jsonb(y)),'[]'::jsonb) into acts from (
    select id, app, account_id, platform, action, target_ref, payload
    from public.growth_social_action s
    where autonomy='auto' and status='queued'
      and (scheduled_at is null or scheduled_at <= now())
      and public.effective_exec_method(s.account_id, s.exec_method) <> 'chrome'
      and (p_app is null or app=p_app)
    order by created_at limit p_limit) y;
  return jsonb_build_object('posts', posts, 'actions', acts);
end $$;

-- Gate the browser worker pull on the social switch.
create or replace function public.social_due_chrome(p_app text default null, p_limit int default 25)
returns jsonb language plpgsql as $$
declare posts jsonb; acts jsonb;
begin
  if not public.social_enabled() then return jsonb_build_object('posts','[]'::jsonb,'actions','[]'::jsonb,'disabled',true); end if;
  select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) into posts from (
    select p.id, p.app, p.account_id, p.platform, p.kind, p.title, p.body, p.hashtags, p.scheduled_at, a.handle, a.owner,
           (select to_jsonb(r) from public.growth_browser_recipe r where r.platform=p.platform and r.action=p.kind limit 1) as recipe
    from public.growth_social_post p join public.growth_channel_account a on a.id=p.account_id
    where p.status in ('scheduled','queued')
      and (p.scheduled_at is null or p.scheduled_at <= now())
      and public.effective_exec_method(p.account_id, p.exec_method)='chrome'
      and (p_app is null or p.app=p_app)
    order by p.scheduled_at nulls first limit p_limit) x;
  select coalesce(jsonb_agg(to_jsonb(y)),'[]'::jsonb) into acts from (
    select s.id, s.app, s.account_id, s.platform, s.action, s.target_ref, s.target_label, s.payload, a.handle, a.owner,
           (select to_jsonb(r) from public.growth_browser_recipe r where r.platform=s.platform and r.action=s.action limit 1) as recipe
    from public.growth_social_action s join public.growth_channel_account a on a.id=s.account_id
    where s.status='queued'
      and (s.scheduled_at is null or s.scheduled_at <= now())
      and public.effective_exec_method(s.account_id, s.exec_method)='chrome'
      and (p_app is null or s.app=p_app)
    order by s.created_at limit p_limit) y;
  return jsonb_build_object('posts', posts, 'actions', acts);
end $$;

-- Enable the social switch (governed, ON) and register the capability + active loops so the
-- orchestration layer knows this module is live.
insert into public.growth_autonomy_switch(scope, key, mode, updated_by, updated_at)
values ('social','', 'on', 'social_omnichannel_build', now())
on conflict (scope, key) do update set mode='on', updated_by=excluded.updated_by, updated_at=now();

insert into public.growth_settings(key, value) values
 ('social_enabled','true'),
 ('social_version','v24-omnichannel+cade'),
 ('social_exec_methods','api,chrome'),
 ('social_loops','metrics_bandit,attribution,atomization,listening,warmup,team_amplify,voice,health,marketplace,cade'),
 ('social_workers','vercel_cron:/api/cron/social-tick;cowork:social-browser-worker;cowork:social-growth-digest')
on conflict (key) do update set value=excluded.value;;

-- GLOBAL SAFETY SEND GATE. Fail-safe: nothing publishes/sends unless the gate is 'active' OR the
-- individual item was human-approved. Default = blocked. Governs the worker pulls (social_due_*),
-- so it holds regardless of per-account autonomy or app code state.

-- Default the gate to BLOCKED only if it doesn't already exist (never clobber a user's choice).
insert into public.growth_autonomy_switch(scope, key, mode, updated_by, updated_at)
values ('send_gate','', 'blocked', 'safety_default', now())
on conflict (scope, key) do nothing;

-- Fail-safe: returns true ONLY when explicitly 'active'; absent/anything-else => blocked.
create or replace function public.send_gate_active()
returns boolean language sql stable as $$
  select coalesce((select mode from public.growth_autonomy_switch where scope='send_gate' and key='') = 'active', false);
$$;

create or replace function public.set_send_gate(p_mode text)
returns text language plpgsql as $$
begin
  insert into public.growth_autonomy_switch(scope, key, mode, updated_by, updated_at)
  values ('send_gate','', case when p_mode='active' then 'active' else 'blocked' end, 'user', now())
  on conflict (scope, key) do update set mode=excluded.mode, updated_by='user', updated_at=now();
  return (select mode from public.growth_autonomy_switch where scope='send_gate' and key='');
end $$;

-- Individually approve ONE item to send even while the gate is blocked (the per-post/email approval).
create or replace function public.approve_send(p_id uuid, p_kind text)
returns jsonb language plpgsql as $$
begin
  if p_kind='post' then
    update public.growth_social_post
       set status='queued', meta = meta || jsonb_build_object('approved_by_human', true, 'approved_at', now())
     where id=p_id;
  else
    update public.growth_social_action
       set status='queued', meta = meta || jsonb_build_object('approved_by_human', true, 'approved_at', now())
     where id=p_id;
  end if;
  return jsonb_build_object('id', p_id, 'kind', p_kind, 'approved', true);
end $$;

-- Re-gate the API worker pull: capability on AND (gate active OR item human-approved).
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
      and (public.send_gate_active() or coalesce((p.meta->>'approved_by_human')::boolean,false))
      and (p_app is null or app=p_app)
    order by scheduled_at nulls first limit p_limit) x;
  select coalesce(jsonb_agg(to_jsonb(y)),'[]'::jsonb) into acts from (
    select id, app, account_id, platform, action, target_ref, payload
    from public.growth_social_action s
    where autonomy='auto' and status='queued'
      and (scheduled_at is null or scheduled_at <= now())
      and public.effective_exec_method(s.account_id, s.exec_method) <> 'chrome'
      and (public.send_gate_active() or coalesce((s.meta->>'approved_by_human')::boolean,false))
      and (p_app is null or app=p_app)
    order by created_at limit p_limit) y;
  return jsonb_build_object('posts', posts, 'actions', acts, 'gate', public.send_gate_active());
end $$;

-- Re-gate the browser worker pull the same way.
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
      and (public.send_gate_active() or coalesce((p.meta->>'approved_by_human')::boolean,false))
      and (p_app is null or p.app=p_app)
    order by p.scheduled_at nulls first limit p_limit) x;
  select coalesce(jsonb_agg(to_jsonb(y)),'[]'::jsonb) into acts from (
    select s.id, s.app, s.account_id, s.platform, s.action, s.target_ref, s.target_label, s.payload, a.handle, a.owner,
           (select to_jsonb(r) from public.growth_browser_recipe r where r.platform=s.platform and r.action=s.action limit 1) as recipe
    from public.growth_social_action s join public.growth_channel_account a on a.id=s.account_id
    where s.status='queued'
      and (s.scheduled_at is null or s.scheduled_at <= now())
      and public.effective_exec_method(s.account_id, s.exec_method)='chrome'
      and (public.send_gate_active() or coalesce((s.meta->>'approved_by_human')::boolean,false))
      and (p_app is null or s.app=p_app)
    order by s.created_at limit p_limit) y;
  return jsonb_build_object('posts', posts, 'actions', acts, 'gate', public.send_gate_active());
end $$;

-- One-glance control status for the UI (both apps read this).
create or replace function public.marketing_control_status(p_app text default null)
returns jsonb language plpgsql stable as $$
begin
  return jsonb_build_object(
    'send_gate', coalesce((select mode from public.growth_autonomy_switch where scope='send_gate' and key=''),'blocked'),
    'email_autonomy', coalesce((select mode from public.growth_autonomy_switch where scope='global' and key=''),'off'),
    'social_capability', public.social_enabled(),
    'connected_accounts', (select count(*) from public.growth_channel_account a where a.status='connected' and (p_app is null or a.app=p_app)),
    'accounts_on_auto', (select count(*) from public.growth_channel_account a where a.autonomy='auto' and (p_app is null or a.app=p_app)),
    'awaiting_approval_posts', (select count(*) from public.growth_social_post p where p.status in ('draft','queued') and coalesce((p.meta->>'approved_by_human')::boolean,false)=false and (p_app is null or p.app=p_app)),
    'awaiting_approval_actions', (select count(*) from public.growth_social_action s where s.status='proposed' and (p_app is null or s.app=p_app)),
    'northstar', public.social_northstar(p_app)
  );
end $$;

-- Register the safety posture in settings so both UIs + the contract verifier see it.
insert into public.growth_settings(key, value) values
 ('social_send_gate','blocked'),
 ('social_safety_note','Fail-safe: nothing posts/sends until send_gate=active OR each item is human-approved (approve_send).')
on conflict (key) do update set value=excluded.value;;

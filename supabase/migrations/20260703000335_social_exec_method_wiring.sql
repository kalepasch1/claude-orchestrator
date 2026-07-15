-- connect_channel_account: honor exec_method from the spec (api | chrome | auto).
create or replace function public.connect_channel_account(p_spec jsonb)
returns jsonb language plpgsql as $$
declare aid uuid; plat text; own text; hndl text;
begin
  plat := coalesce(p_spec->>'platform','linkedin_personal');
  own  := coalesce(p_spec->>'owner','personal');
  hndl := p_spec->>'handle';
  insert into public.growth_channel_account(app, platform, owner, handle, display_name, workspace_id,
      actor_hash, brand_mode, credential_method, credential_ref, scopes, autonomy, exec_method, status, meta)
  values (coalesce(p_spec->>'app','apparently'), plat, own, hndl, p_spec->>'display_name',
      p_spec->>'workspace_id', p_spec->>'actor_hash', coalesce(p_spec->>'brand_mode', own),
      coalesce(p_spec->>'credential_method',(select credential_method from public.growth_channel_catalog where platform=plat),'oauth'),
      p_spec->>'credential_ref',
      coalesce((select array_agg(x) from jsonb_array_elements_text(p_spec->'scopes') x),'{}'),
      coalesce(p_spec->>'autonomy','approval'), coalesce(p_spec->>'exec_method','api'),
      coalesce(p_spec->>'status','pending'), coalesce(p_spec->'meta','{}'::jsonb))
  on conflict (app, platform, owner, handle) do update
     set display_name=coalesce(excluded.display_name, growth_channel_account.display_name),
         credential_ref=coalesce(excluded.credential_ref, growth_channel_account.credential_ref),
         credential_method=excluded.credential_method, exec_method=excluded.exec_method,
         autonomy=excluded.autonomy, status=excluded.status, updated_at=now()
  returning id into aid;
  if (p_spec ? 'secret_ref') or (p_spec ? 'oauth_account_ref') then
    insert into public.growth_channel_credential(account_id, method, secret_ref, oauth_account_ref, status)
    values (aid, coalesce(p_spec->>'credential_method','oauth'), p_spec->>'secret_ref', p_spec->>'oauth_account_ref', 'stored');
  end if;
  return jsonb_build_object('account_id', aid, 'platform', plat, 'owner', own, 'status', coalesce(p_spec->>'status','pending'));
end $$;

-- set_channel_account: allow patching exec_method too.
create or replace function public.set_channel_account(p_account_id uuid, p_patch jsonb)
returns void language plpgsql as $$
begin
  update public.growth_channel_account set
    status = coalesce(p_patch->>'status', status),
    autonomy = coalesce(p_patch->>'autonomy', autonomy),
    exec_method = coalesce(p_patch->>'exec_method', exec_method),
    handle = coalesce(p_patch->>'handle', handle),
    display_name = coalesce(p_patch->>'display_name', display_name),
    updated_at = now()
  where id = p_account_id;
end $$;

-- social_due_now (API path): skip items that resolve to the chrome exec method (the browser worker
-- handles those via social_due_chrome), so the two workers never double-execute.
create or replace function public.social_due_now(p_app text default null, p_limit int default 25)
returns jsonb language plpgsql as $$
declare posts jsonb; acts jsonb;
begin
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
end $$;;

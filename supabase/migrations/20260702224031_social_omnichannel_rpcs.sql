-- RPCs for the omnichannel social layer. All self-contained + idempotent.

-- Connect (upsert) a channel account from a spec. Stores only a credential pointer.
create or replace function public.connect_channel_account(p_spec jsonb)
returns jsonb language plpgsql as $$
declare aid uuid; plat text; own text; hndl text;
begin
  plat := coalesce(p_spec->>'platform','linkedin_personal');
  own  := coalesce(p_spec->>'owner','personal');
  hndl := p_spec->>'handle';
  insert into public.growth_channel_account(app, platform, owner, handle, display_name, workspace_id,
      actor_hash, brand_mode, credential_method, credential_ref, scopes, autonomy, status, meta)
  values (coalesce(p_spec->>'app','apparently'), plat, own, hndl, p_spec->>'display_name',
      p_spec->>'workspace_id', p_spec->>'actor_hash', coalesce(p_spec->>'brand_mode', own),
      coalesce(p_spec->>'credential_method',(select credential_method from public.growth_channel_catalog where platform=plat),'oauth'),
      p_spec->>'credential_ref',
      coalesce((select array_agg(x) from jsonb_array_elements_text(p_spec->'scopes') x),'{}'),
      coalesce(p_spec->>'autonomy','approval'),
      coalesce(p_spec->>'status','pending'), coalesce(p_spec->'meta','{}'::jsonb))
  on conflict (app, platform, owner, handle) do update
     set display_name=coalesce(excluded.display_name, growth_channel_account.display_name),
         credential_ref=coalesce(excluded.credential_ref, growth_channel_account.credential_ref),
         credential_method=excluded.credential_method,
         autonomy=excluded.autonomy, status=excluded.status, updated_at=now()
  returning id into aid;
  if (p_spec ? 'secret_ref') or (p_spec ? 'oauth_account_ref') then
    insert into public.growth_channel_credential(account_id, method, secret_ref, oauth_account_ref, status)
    values (aid, coalesce(p_spec->>'credential_method','oauth'), p_spec->>'secret_ref', p_spec->>'oauth_account_ref', 'stored');
  end if;
  return jsonb_build_object('account_id', aid, 'platform', plat, 'owner', own, 'status',
    coalesce(p_spec->>'status','pending'));
end $$;

create or replace function public.set_channel_account(p_account_id uuid, p_patch jsonb)
returns void language plpgsql as $$
begin
  update public.growth_channel_account set
    status = coalesce(p_patch->>'status', status),
    autonomy = coalesce(p_patch->>'autonomy', autonomy),
    handle = coalesce(p_patch->>'handle', handle),
    display_name = coalesce(p_patch->>'display_name', display_name),
    updated_at = now()
  where id = p_account_id;
end $$;

-- Schedule a social post (draft/queued/scheduled).
create or replace function public.schedule_social_post(p jsonb)
returns uuid language plpgsql as $$
declare pid uuid;
begin
  insert into public.growth_social_post(app, account_id, platform, campaign_id, scheme_run_id, content_id,
      kind, title, body, hashtags, autonomy, scheduled_at, status, meta)
  values (coalesce(p->>'app','apparently'), (p->>'account_id')::uuid, p->>'platform',
      nullif(p->>'campaign_id','')::uuid, nullif(p->>'scheme_run_id','')::uuid, nullif(p->>'content_id','')::uuid,
      coalesce(p->>'kind','post'), p->>'title', p->>'body',
      coalesce((select array_agg(x) from jsonb_array_elements_text(p->'hashtags') x),'{}'),
      coalesce(p->>'autonomy','approval'), nullif(p->>'scheduled_at','')::timestamptz,
      coalesce(p->>'status','draft'), coalesce(p->'meta','{}'::jsonb))
  returning id into pid;
  return pid;
end $$;

-- Enqueue an engagement action, guarding the per-platform+action daily cap.
create or replace function public.enqueue_social_action(p jsonb)
returns jsonb language plpgsql as $$
declare aid uuid; plat text; act text; cap int; used int; today date := (now() at time zone 'utc')::date; nid uuid;
begin
  aid := (p->>'account_id')::uuid; act := p->>'action';
  plat := coalesce(p->>'platform', (select platform from public.growth_channel_account where id=aid));
  cap := coalesce((select daily_cap from public.growth_rate_policy where platform=plat and action=act),
                  (select daily_action_cap from public.growth_channel_account where id=aid), 20);
  select count(*) into used from public.growth_social_action
   where account_id=aid and action=act and rate_bucket=today and status in ('queued','scheduled','done');
  if used >= cap then
    insert into public.growth_social_action(app, account_id, platform, action, target_ref, target_label, payload,
        scheme_run_id, autonomy, status, meta)
    values (coalesce(p->>'app','apparently'), aid, plat, act, p->>'target_ref', p->>'target_label',
        coalesce(p->'payload','{}'::jsonb), nullif(p->>'scheme_run_id','')::uuid,
        coalesce(p->>'autonomy','approval'),'rate_limited', jsonb_build_object('cap',cap,'used',used))
    returning id into nid;
    return jsonb_build_object('action_id', nid, 'status','rate_limited','cap',cap,'used',used);
  end if;
  insert into public.growth_social_action(app, account_id, platform, action, target_ref, target_label, payload,
      scheme_run_id, autonomy, scheduled_at, status, meta)
  values (coalesce(p->>'app','apparently'), aid, plat, act, p->>'target_ref', p->>'target_label',
      coalesce(p->'payload','{}'::jsonb), nullif(p->>'scheme_run_id','')::uuid,
      coalesce(p->>'autonomy','approval'), nullif(p->>'scheduled_at','')::timestamptz,
      case when coalesce(p->>'autonomy','approval')='auto' then 'queued' else 'proposed' end,
      coalesce(p->'meta','{}'::jsonb))
  returning id into nid;
  return jsonb_build_object('action_id', nid, 'status','queued','cap',cap,'used',used);
end $$;

-- Recommend schemes for an app/owner (catalog + play-derived), scored.
create or replace function public.recommend_schemes(p_app text default 'apparently', p_owner text default 'personal')
returns jsonb language plpgsql as $$
declare out jsonb;
begin
  select coalesce(jsonb_agg(to_jsonb(s) order by s.score desc), '[]'::jsonb) into out
  from public.growth_scheme s
  where s.status='active' and (s.owner_default = p_owner or p_owner is null);
  return out;
end $$;

-- Apply a scheme to accounts: creates calendar cadence + seeds first drafts + engagement actions.
create or replace function public.apply_scheme(p_scheme_id uuid, p_account_ids uuid[], p_app text default 'apparently', p_mode text default 'approval')
returns jsonb language plpgsql as $$
declare sc public.growth_scheme; run_id uuid; aid uuid; cad jsonb; actj jsonb; plat text; made_cal int := 0; made_post int := 0; made_act int := 0;
begin
  select * into sc from public.growth_scheme where id=p_scheme_id;
  if not found then raise exception 'scheme % not found', p_scheme_id; end if;
  insert into public.growth_scheme_run(scheme_id, app, account_ids, mode, status)
  values (p_scheme_id, p_app, coalesce(p_account_ids,'{}'), p_mode, 'active') returning id into run_id;

  foreach aid in array coalesce(p_account_ids,'{}') loop
    plat := (select platform from public.growth_channel_account where id=aid);
    -- cadence entries
    for cad in select * from jsonb_array_elements(coalesce(sc.spec->'cadence','[]'::jsonb)) loop
      if (cad->>'platform') is null or cad->>'platform' = plat then
        insert into public.growth_content_calendar(app, account_id, platform, kind, cadence, per_period, topic_hint, scheme_run_id, next_due, active, meta)
        values (p_app, aid, plat, coalesce(cad->>'kind','post'), coalesce(cad->>'cadence','weekly'),
                coalesce((cad->>'per_period')::int,1), cad->>'topic_hint', run_id, now(), true, cad);
        made_cal := made_cal + 1;
        -- seed one initial draft per cadence line
        insert into public.growth_social_post(app, account_id, platform, scheme_run_id, kind, title, body, autonomy, status, meta)
        values (p_app, aid, plat, run_id, coalesce(cad->>'kind','post'),
                coalesce(cad->>'topic_hint', sc.name), null, p_mode, 'draft',
                jsonb_build_object('needs_generation', true, 'scheme', sc.slug));
        made_post := made_post + 1;
      end if;
    end loop;
    -- engagement actions (as proposals; worker/tick fills targets)
    for actj in select * from jsonb_array_elements(coalesce(sc.spec->'actions','[]'::jsonb)) loop
      if (actj->>'platform') is null or actj->>'platform' = plat then
        insert into public.growth_social_action(app, account_id, platform, action, scheme_run_id, autonomy, status, meta)
        values (p_app, aid, plat, coalesce(actj->>'action','like'), run_id, p_mode, 'proposed',
                jsonb_build_object('per_day',(actj->>'per_day'),'scheme',sc.slug));
        made_act := made_act + 1;
      end if;
    end loop;
  end loop;
  return jsonb_build_object('scheme_run_id', run_id, 'calendar', made_cal, 'drafts', made_post,
    'actions', made_act, 'mode', p_mode,
    'note', 'Scheme applied. Drafts staged for generation; nothing publishes until mode=auto or you approve.');
end $$;

-- Worker pull: items due now (auto-mode posts + queued actions within caps).
create or replace function public.social_due_now(p_app text default null, p_limit int default 25)
returns jsonb language plpgsql as $$
declare posts jsonb; acts jsonb;
begin
  select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) into posts from (
    select id, app, account_id, platform, kind, title, body, scheduled_at
    from public.growth_social_post
    where autonomy='auto' and status in ('scheduled','queued')
      and (scheduled_at is null or scheduled_at <= now())
      and (p_app is null or app=p_app)
    order by scheduled_at nulls first limit p_limit) x;
  select coalesce(jsonb_agg(to_jsonb(y)),'[]'::jsonb) into acts from (
    select id, app, account_id, platform, action, target_ref, payload
    from public.growth_social_action
    where autonomy='auto' and status='queued'
      and (scheduled_at is null or scheduled_at <= now())
      and (p_app is null or app=p_app)
    order by created_at limit p_limit) y;
  return jsonb_build_object('posts', posts, 'actions', acts);
end $$;

-- Record the outcome of a post or action (called by the send/handoff worker).
create or replace function public.mark_social_result(p_id uuid, p_kind text, p_status text, p_url text default null, p_metrics jsonb default '{}'::jsonb)
returns void language plpgsql as $$
begin
  if p_kind='post' then
    update public.growth_social_post set status=p_status, external_url=coalesce(p_url,external_url),
       metrics = metrics || coalesce(p_metrics,'{}'::jsonb), updated_at=now() where id=p_id;
  else
    update public.growth_social_action set status=p_status, external_url=coalesce(p_url,external_url),
       meta = meta || coalesce(p_metrics,'{}'::jsonb), updated_at=now() where id=p_id;
  end if;
end $$;

-- Dashboard rollup.
create or replace function public.social_rollup(p_app text default null)
returns jsonb language plpgsql as $$
declare out jsonb;
begin
  select jsonb_build_object(
    'accounts', (select count(*) from public.growth_channel_account a where p_app is null or a.app=p_app),
    'connected', (select count(*) from public.growth_channel_account a where (p_app is null or a.app=p_app) and a.status='connected'),
    'posts_by_status', (select coalesce(jsonb_object_agg(status,c),'{}'::jsonb) from (select status,count(*) c from public.growth_social_post where p_app is null or app=p_app group by status) s),
    'actions_by_status', (select coalesce(jsonb_object_agg(status,c),'{}'::jsonb) from (select status,count(*) c from public.growth_social_action where p_app is null or app=p_app group by status) s),
    'active_scheme_runs', (select count(*) from public.growth_scheme_run r where (p_app is null or r.app=p_app) and r.status='active'),
    'active_cadence', (select count(*) from public.growth_content_calendar c where (p_app is null or c.app=p_app) and c.active)
  ) into out;
  return out;
end $$;;

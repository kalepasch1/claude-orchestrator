-- Closed flywheel (metrics → bandit → scheme auto-promote) + deliverability (jitter, sessions,
-- swarm amplification). Idempotent.

-- Deliverability: per-account session metadata the browser worker uses (proxy/UA/timezone).
create table if not exists public.growth_account_session (
  account_id uuid primary key references public.growth_channel_account(id) on delete cascade,
  proxy text, user_agent text, timezone text, notes text,
  updated_at timestamptz not null default now()
);
alter table public.growth_account_session enable row level security;

-- Deliverability: jittered next slot for an action, respecting the platform min-gap + a random spread.
create or replace function public.next_slot(p_account_id uuid, p_action text, p_jitter_max_sec int default 900)
returns timestamptz language plpgsql stable as $$
declare gap int; last_at timestamptz; base timestamptz;
begin
  select min_gap_seconds into gap from public.growth_rate_policy
   where platform=(select platform from public.growth_channel_account where id=p_account_id) and action=p_action;
  gap := coalesce(gap, 60);
  select max(coalesce(scheduled_at, created_at)) into last_at from public.growth_social_action
   where account_id=p_account_id and status in ('queued','scheduled');
  base := greatest(now(), coalesce(last_at, now()) + make_interval(secs => gap));
  return base + make_interval(secs => floor(random()*p_jitter_max_sec)::int);
end $$;

-- Upgraded enqueue: warmup caps + health pause + auto-jittered scheduling for auto actions.
create or replace function public.enqueue_social_action(p jsonb)
returns jsonb language plpgsql as $$
declare aid uuid; plat text; act text; base_cap int; cap int; used int; today date := (now() at time zone 'utc')::date; nid uuid; hstat text; auto_mode boolean; sched timestamptz;
begin
  aid := (p->>'account_id')::uuid; act := p->>'action';
  plat := coalesce(p->>'platform', (select platform from public.growth_channel_account where id=aid));
  auto_mode := coalesce(p->>'autonomy','approval')='auto';
  select status into hstat from public.growth_account_health where account_id=aid;
  if hstat = 'paused' then
    insert into public.growth_social_action(app, account_id, platform, action, target_ref, target_label, payload, scheme_run_id, autonomy, status, meta)
    values (coalesce(p->>'app','apparently'), aid, plat, act, p->>'target_ref', p->>'target_label', coalesce(p->'payload','{}'::jsonb),
            nullif(p->>'scheme_run_id','')::uuid, coalesce(p->>'autonomy','approval'),'skipped', jsonb_build_object('reason','account_paused'))
    returning id into nid;
    return jsonb_build_object('action_id', nid, 'status','skipped','reason','account_paused');
  end if;
  base_cap := coalesce((select daily_cap from public.growth_rate_policy where platform=plat and action=act),
                       (select daily_action_cap from public.growth_channel_account where id=aid), 20);
  cap := greatest(1, floor(base_cap * public.warmup_multiplier(aid))::int);
  select count(*) into used from public.growth_social_action
   where account_id=aid and action=act and rate_bucket=today and status in ('queued','scheduled','done');
  if used >= cap then
    insert into public.growth_social_action(app, account_id, platform, action, target_ref, target_label, payload, scheme_run_id, autonomy, status, meta)
    values (coalesce(p->>'app','apparently'), aid, plat, act, p->>'target_ref', p->>'target_label', coalesce(p->'payload','{}'::jsonb),
            nullif(p->>'scheme_run_id','')::uuid, coalesce(p->>'autonomy','approval'),'rate_limited', jsonb_build_object('cap',cap,'used',used,'base_cap',base_cap))
    returning id into nid;
    return jsonb_build_object('action_id', nid, 'status','rate_limited','cap',cap,'used',used);
  end if;
  sched := coalesce(nullif(p->>'scheduled_at','')::timestamptz, case when auto_mode then public.next_slot(aid, act) else null end);
  insert into public.growth_social_action(app, account_id, platform, action, target_ref, target_label, payload, scheme_run_id, autonomy, scheduled_at, status, meta)
  values (coalesce(p->>'app','apparently'), aid, plat, act, p->>'target_ref', p->>'target_label', coalesce(p->'payload','{}'::jsonb),
      nullif(p->>'scheme_run_id','')::uuid, coalesce(p->>'autonomy','approval'), sched,
      case when auto_mode then 'queued' else 'proposed' end, coalesce(p->'meta','{}'::jsonb))
  returning id into nid;
  return jsonb_build_object('action_id', nid, 'status', case when auto_mode then 'queued' else 'proposed' end,'cap',cap,'used',used,'scheduled_at',sched);
end $$;

-- (1) Bandit: assign the best-performing variant to a post before it's generated/sent.
create or replace function public.assign_best_variant(p_post_id uuid, p_experiment_id uuid)
returns jsonb language plpgsql as $$
declare v jsonb;
begin
  v := public.pick_variant(p_experiment_id);
  if v is null then return null; end if;
  update public.growth_social_post set variant_id=(v->>'variant_id')::uuid where id=p_post_id;
  return v;
end $$;

-- (2) Compute per-scheme-run outcomes from its posts' engagement (feeds auto-promotion + marketplace).
create or replace function public.compute_scheme_outcomes()
returns int language plpgsql as $$
declare n int;
begin
  with agg as (
    select r.id run_id,
      count(p.*) filter (where p.status='posted') posted,
      count(p.*) total,
      avg( least(1.0, (coalesce((p.metrics->>'likes')::numeric,0)+coalesce((p.metrics->>'comments')::numeric,0)
           +coalesce((p.metrics->>'shares')::numeric,0)+coalesce((p.metrics->>'clicks')::numeric,0))
           / greatest(coalesce((p.metrics->>'impressions')::numeric,0),1)) ) filter (where p.status='posted') avg_reward,
      sum(coalesce((p.metrics->>'impressions')::numeric,0)) impressions
    from public.growth_scheme_run r left join public.growth_social_post p on p.scheme_run_id=r.id
    group by r.id)
  update public.growth_scheme_run r
     set outcome_score = coalesce(agg.avg_reward,0),
         outcome_stats = jsonb_build_object('posted',agg.posted,'total',agg.total,'avg_reward',round(coalesce(agg.avg_reward,0),4),'impressions',agg.impressions)
    from agg where agg.run_id=r.id;
  get diagnostics n = row_count; return n;
end $$;

-- (2)/(8) Auto-promote proven runs into the shared marketplace (min posts + score gates).
create or replace function public.auto_promote_schemes(p_min_posted int default 3, p_min_score numeric default 0.03)
returns jsonb language plpgsql as $$
declare rec record; promoted int := 0; slug text;
begin
  perform public.compute_scheme_outcomes();
  for rec in
    select r.*, s.name base_name from public.growth_scheme_run r join public.growth_scheme s on s.id=r.scheme_id
    where r.status='active' and coalesce((r.outcome_stats->>'posted')::int,0) >= p_min_posted and r.outcome_score >= p_min_score
  loop
    slug := 'proven-'||left(regexp_replace(lower(rec.base_name),'[^a-z0-9]+','-','g'),32)||'-'||left(rec.id::text,8);
    perform public.promote_scheme_run(rec.id, rec.base_name||' (proven)', slug);
    update public.growth_scheme set uses = uses + 1 where id = rec.scheme_id;
    promoted := promoted + 1;
  end loop;
  return jsonb_build_object('promoted', promoted);
end $$;

-- (3) Auto-amplify: upgraded mark_social_result — when a post is posted and auto-amplify is on,
-- sibling connected accounts (same app + platform) like it (swarm effect). Gated by a setting.
create or replace function public.mark_social_result(p_id uuid, p_kind text, p_status text, p_url text default null, p_metrics jsonb default '{}'::jsonb)
returns void language plpgsql as $$
declare pst public.growth_social_post; sibs uuid[]; amp_on boolean;
begin
  if p_kind='post' then
    update public.growth_social_post set status=p_status, external_url=coalesce(p_url,external_url),
       metrics = metrics || coalesce(p_metrics,'{}'::jsonb), updated_at=now() where id=p_id returning * into pst;
    if p_status='posted' then
      select coalesce((select value='true' from public.growth_settings where key='social_auto_amplify'), false) into amp_on;
      if amp_on then
        select array_agg(id) into sibs from (
          select a.id from public.growth_channel_account a
          where a.app=pst.app and a.platform=pst.platform and a.id<>pst.account_id
            and a.status='connected' and a.autonomy<>'off' limit 5) s;
        if sibs is not null and array_length(sibs,1) > 0 then perform public.team_amplify(pst.id, sibs, false); end if;
      end if;
    end if;
  else
    update public.growth_social_action set status=p_status, external_url=coalesce(p_url,external_url),
       meta = meta || coalesce(p_metrics,'{}'::jsonb), updated_at=now() where id=p_id;
  end if;
end $$;;

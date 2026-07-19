-- (5) Warmup multiplier for an account (1.0 if no warmup row).
create or replace function public.warmup_multiplier(p_account_id uuid)
returns numeric language sql stable as $$
  select coalesce((select least(1.0, cap_multiplier)::numeric from public.growth_account_warmup where account_id=p_account_id), 1.0);
$$;

-- (5)/(7) Upgraded enqueue: warmup-scaled caps + health auto-pause. Supersedes the v23 version.
create or replace function public.enqueue_social_action(p jsonb)
returns jsonb language plpgsql as $$
declare aid uuid; plat text; act text; base_cap int; cap int; used int; today date := (now() at time zone 'utc')::date; nid uuid; hstat text;
begin
  aid := (p->>'account_id')::uuid; act := p->>'action';
  plat := coalesce(p->>'platform', (select platform from public.growth_channel_account where id=aid));
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
  insert into public.growth_social_action(app, account_id, platform, action, target_ref, target_label, payload, scheme_run_id, autonomy, scheduled_at, status, meta)
  values (coalesce(p->>'app','apparently'), aid, plat, act, p->>'target_ref', p->>'target_label', coalesce(p->'payload','{}'::jsonb),
      nullif(p->>'scheme_run_id','')::uuid, coalesce(p->>'autonomy','approval'), nullif(p->>'scheduled_at','')::timestamptz,
      case when coalesce(p->>'autonomy','approval')='auto' then 'queued' else 'proposed' end, coalesce(p->'meta','{}'::jsonb))
  returning id into nid;
  return jsonb_build_object('action_id', nid, 'status','queued','cap',cap,'used',used);
end $$;

-- (5) Advance warmup ramps (call daily from cron). 0.25 -> 1.0 across max_ramp_days.
create or replace function public.tick_warmup()
returns int language plpgsql as $$
declare n int;
begin
  update public.growth_account_warmup
     set day = day + 1,
         cap_multiplier = least(1.0, 0.25 + 0.75 * (day::numeric / greatest(max_ramp_days,1)))
   where cap_multiplier < 1.0;
  get diagnostics n = row_count; return n;
end $$;

-- (1) Bandit: pick the best variant (UCB; untried variants win first).
create or replace function public.pick_variant(p_experiment_id uuid)
returns jsonb language plpgsql as $$
declare tot int; v public.growth_social_variant;
begin
  select coalesce(sum(trials),0) into tot from public.growth_social_variant where experiment_id=p_experiment_id;
  select * into v from public.growth_social_variant where experiment_id=p_experiment_id
   order by case when trials=0 then 1e9
     else (reward_sum/nullif(trials,0)) + sqrt(2*ln(tot+1)/nullif(trials,0)) end desc limit 1;
  if not found then return null; end if;
  return jsonb_build_object('variant_id', v.id, 'label', v.label, 'spec', v.spec, 'trials', v.trials,
     'mean_reward', case when v.trials>0 then round(v.reward_sum/v.trials,4) else null end);
end $$;

-- (1) Record engagement metrics on a post + update its variant's bandit stats.
create or replace function public.record_post_metrics(p_post_id uuid, p_metrics jsonb)
returns void language plpgsql as $$
declare vid uuid; imp numeric; eng numeric; reward numeric;
begin
  update public.growth_social_post set metrics = metrics || coalesce(p_metrics,'{}'::jsonb), updated_at=now()
   where id=p_post_id returning variant_id into vid;
  if vid is not null then
    imp := greatest(coalesce((p_metrics->>'impressions')::numeric,0),1);
    eng := coalesce((p_metrics->>'likes')::numeric,0)+coalesce((p_metrics->>'comments')::numeric,0)
         + coalesce((p_metrics->>'shares')::numeric,0)+coalesce((p_metrics->>'clicks')::numeric,0);
    reward := least(1.0, eng/imp);
    update public.growth_social_variant set trials=trials+1, reward_sum=reward_sum+reward where id=vid;
  end if;
end $$;

-- (2) Tracked links + click/attribution.
create or replace function public.create_tracked_link(p jsonb)
returns jsonb language plpgsql as $$
declare s text;
begin
  s := coalesce(p->>'slug', substr(md5(random()::text||clock_timestamp()::text),1,10));
  insert into public.growth_social_link(app, post_id, platform, slug, destination, utm)
  values (coalesce(p->>'app','apparently'), nullif(p->>'post_id','')::uuid, p->>'platform', s, p->>'destination', coalesce(p->'utm','{}'::jsonb));
  if p ? 'post_id' then update public.growth_social_post set tracked_slug=s where id=(p->>'post_id')::uuid; end if;
  return jsonb_build_object('slug', s);
end $$;

create or replace function public.record_link_click(p_slug text)
returns text language plpgsql as $$
declare dest text;
begin
  update public.growth_social_link set clicks=clicks+1 where slug=p_slug returning destination into dest;
  return dest;
end $$;

create or replace function public.social_attribution(p_app text default null)
returns jsonb language plpgsql as $$
declare out jsonb;
begin
  select coalesce(jsonb_agg(to_jsonb(x) order by x.clicks desc),'[]'::jsonb) into out from (
    select coalesce(platform,'unknown') platform, sum(clicks) clicks, sum(conversions) conversions, sum(revenue) revenue
    from public.growth_social_link where (p_app is null or app=p_app) group by 1) x;
  return out;
end $$;

-- (4) Ingest a listening signal; if an active rule matches, enqueue a reactive engagement action.
create or replace function public.ingest_signal(p jsonb)
returns jsonb language plpgsql as $$
declare sid uuid; r public.growth_listen_rule; enq jsonb;
begin
  insert into public.growth_social_signal(app, platform, kind, source_ref, author, text, score)
  values (coalesce(p->>'app','apparently'), p->>'platform', coalesce(p->>'kind','keyword'), p->>'source_ref', p->>'author', p->>'text', coalesce((p->>'score')::numeric,0.5))
  returning id into sid;
  select * into r from public.growth_listen_rule
   where active and app=coalesce(p->>'app','apparently') and platform=p->>'platform'
     and position(lower(query) in lower(coalesce(p->>'text',''))) > 0
   order by created_at limit 1;
  if found and r.account_id is not null then
    enq := public.enqueue_social_action(jsonb_build_object('app',r.app,'account_id',r.account_id,'platform',r.platform,
      'action',r.action,'target_ref',p->>'source_ref','target_label',p->>'author','autonomy',r.autonomy,
      'meta',jsonb_build_object('reactive',true,'signal_id',sid)));
    update public.growth_social_signal set status='acted' where id=sid;
    return jsonb_build_object('signal_id',sid,'reactive',enq);
  end if;
  return jsonb_build_object('signal_id',sid,'reactive',null);
end $$;

-- (5) Team amplification: teammates like/comment a just-published post.
create or replace function public.team_amplify(p_post_id uuid, p_account_ids uuid[], p_comment boolean default false)
returns jsonb language plpgsql as $$
declare pst public.growth_social_post; aid uuid; tgt text; n int := 0;
begin
  select * into pst from public.growth_social_post where id=p_post_id;
  if not found then raise exception 'post % not found', p_post_id; end if;
  tgt := coalesce(pst.external_url, 'post:'||p_post_id::text);
  foreach aid in array coalesce(p_account_ids,'{}') loop
    perform public.enqueue_social_action(jsonb_build_object('app',pst.app,'account_id',aid,'platform',pst.platform,
      'action','like','target_ref',tgt,'autonomy','auto','meta',jsonb_build_object('amplify',p_post_id)));
    n := n+1;
    if p_comment then
      perform public.enqueue_social_action(jsonb_build_object('app',pst.app,'account_id',aid,'platform',pst.platform,
        'action','comment','target_ref',tgt,'autonomy','approval','meta',jsonb_build_object('amplify',p_post_id)));
    end if;
  end loop;
  return jsonb_build_object('amplified', n, 'target', tgt);
end $$;

-- (6) Upsert a voice profile.
create or replace function public.set_voice_profile(p jsonb)
returns void language plpgsql as $$
begin
  insert into public.growth_voice_profile(account_id, app, tone, examples, dos, donts, updated_at)
  values ((p->>'account_id')::uuid, coalesce(p->>'app','apparently'), p->>'tone',
          coalesce(p->'examples','[]'::jsonb), coalesce(p->'dos','[]'::jsonb), coalesce(p->'donts','[]'::jsonb), now())
  on conflict (account_id) do update set tone=excluded.tone, examples=excluded.examples,
    dos=excluded.dos, donts=excluded.donts, updated_at=now();
end $$;

-- (7) Record action outcome into account health; auto-pause on shadowban signal or high failure.
create or replace function public.record_action_health(p_account_id uuid, p_ok boolean, p_signal text default null)
returns jsonb language plpgsql as $$
declare h public.growth_account_health; okc int; failc int; newstat text;
begin
  insert into public.growth_account_health(account_id) values (p_account_id) on conflict (account_id) do nothing;
  update public.growth_account_health
     set action_ok = action_ok + case when p_ok then 1 else 0 end,
         action_fail = action_fail + case when p_ok then 0 else 1 end,
         signals = case when p_signal is null then signals else (signals || to_jsonb(p_signal)) end,
         last_checked = now()
   where account_id=p_account_id returning * into h;
  okc := h.action_ok; failc := h.action_fail;
  newstat := case
    when p_signal in ('shadowban','captcha','checkpoint','blocked') then 'paused'
    when (okc+failc) >= 10 and failc::numeric/(okc+failc) > 0.3 then 'paused'
    when (okc+failc) >= 5 and failc::numeric/nullif(okc+failc,0) > 0.15 then 'watch'
    else h.status end;
  if newstat <> h.status then
    update public.growth_account_health set status=newstat where account_id=p_account_id;
    if newstat='paused' then update public.growth_channel_account set autonomy='off' where id=p_account_id; end if;
  end if;
  return jsonb_build_object('status', newstat, 'ok', okc, 'fail', failc);
end $$;

-- (8) Promote a high-performing scheme run into a shareable marketplace scheme.
create or replace function public.promote_scheme_run(p_run_id uuid, p_name text, p_slug text)
returns jsonb language plpgsql as $$
declare rn public.growth_scheme_run; base public.growth_scheme; nid uuid;
begin
  select * into rn from public.growth_scheme_run where id=p_run_id;
  if not found then raise exception 'run % not found', p_run_id; end if;
  select * into base from public.growth_scheme where id=rn.scheme_id;
  insert into public.growth_scheme(slug, name, objective, owner_default, platforms, spec, recommended_for, source, score, outcome_stats)
  values (p_slug, p_name, coalesce(base.objective,'authority'), coalesce(base.owner_default,'personal'),
          coalesce(base.platforms,'{}'), coalesce(base.spec,'{}'::jsonb),
          jsonb_build_object('promoted_from', rn.scheme_id, 'who', 'proven by real outcomes'),
          'promoted', greatest(0.5, coalesce(rn.outcome_score,0.5)), coalesce(rn.outcome_stats,'{}'::jsonb))
  on conflict (slug) do update set score=excluded.score, outcome_stats=excluded.outcome_stats, spec=excluded.spec
  returning id into nid;
  return jsonb_build_object('scheme_id', nid, 'slug', p_slug);
end $$;

create or replace function public.rank_marketplace(p_objective text default null)
returns jsonb language plpgsql as $$
declare out jsonb;
begin
  select coalesce(jsonb_agg(to_jsonb(s) order by s.score desc, s.uses desc),'[]'::jsonb) into out
  from public.growth_scheme s where s.status='active' and (p_objective is null or s.objective=p_objective);
  return out;
end $$;;

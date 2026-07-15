-- (1) REFERRAL PRIMITIVE — the top-ranked play (compounding, zero human cost) as real machinery.
create table if not exists public.growth_referral (
  id uuid primary key default gen_random_uuid(),
  app text not null,
  referrer_ref text not null,                 -- the referring user's opaque id
  slug text not null,                          -- tracked-link slug handed to that user
  invites int not null default 0,
  signups int not null default 0,
  created_at timestamptz not null default now(),
  unique (app, referrer_ref)
);
alter table public.growth_referral enable row level security;

create or replace function public.issue_referral_link(p_app text, p_user_ref text, p_destination text default null)
returns jsonb language plpgsql as $$
declare v_slug text; existing text;
begin
  select slug into existing from public.growth_referral where app=p_app and referrer_ref=p_user_ref;
  if existing is not null then return jsonb_build_object('slug', existing, 'reused', true); end if;
  v_slug := (public.create_tracked_link(jsonb_build_object(
     'app', p_app, 'platform','referral', 'destination', coalesce(p_destination,'https://'||p_app),
     'utm', jsonb_build_object('source','referral','ref',p_user_ref))))->>'slug';
  insert into public.growth_referral(app, referrer_ref, slug) values (p_app, p_user_ref, v_slug);
  return jsonb_build_object('slug', v_slug, 'reused', false);
end $$;

-- credit the referrer when a signup arrives via their slug (k-factor becomes measurable)
create or replace function public.credit_referral(p_slug text)
returns void language sql as $$
  update public.growth_referral set signups = signups + 1 where slug = p_slug;
$$;

create or replace function public.referral_rollup(p_app text default null)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'referrers', (select count(*) from public.growth_referral r where (p_app is null or r.app=p_app)),
    'referred_signups', (select coalesce(sum(r.signups),0) from public.growth_referral r where (p_app is null or r.app=p_app)),
    'k_factor', (select round(coalesce(sum(r.signups),0)::numeric / greatest(count(*),1), 3)
                 from public.growth_referral r where (p_app is null or r.app=p_app)));
$$;

-- record_signup now also credits the referrer
create or replace function public.record_signup(p jsonb)
returns jsonb language plpgsql as $$
declare v_app text; v_ref text; v_slug text; v_channel text; v_rev numeric; v_attr text; v_run uuid; existed boolean;
begin
  v_app := coalesce(p->>'app','unknown');
  v_ref := coalesce(p->>'external_user_ref', p->>'userRef');
  if v_ref is null then raise exception 'external_user_ref required'; end if;
  v_slug := nullif(p->>'slug',''); v_channel := nullif(p->>'channel','');
  v_rev := coalesce((p->>'revenue')::numeric, 0);
  if v_channel is null and v_slug is not null then
    select 'social:'||coalesce(l.platform,'unknown') into v_channel from public.growth_social_link l where l.slug=v_slug;
  end if;
  v_attr := case when v_slug is not null then 'link:'||v_slug when v_channel is not null then 'channel:'||v_channel else 'direct' end;
  insert into public.growth_signup_event(app, external_user_ref, channel, source_ref, slug, campaign, revenue, attributed_to, meta)
  values (v_app, v_ref, v_channel, p->>'source_ref', v_slug, p->>'campaign', v_rev, v_attr, coalesce(p->'meta','{}'::jsonb))
  on conflict (app, external_user_ref) do nothing;
  get diagnostics existed = row_count;
  if not existed then return jsonb_build_object('recorded', false, 'reason','already_counted','app',v_app,'ref',v_ref); end if;
  if v_slug is not null then
    perform public.record_link_conversion(v_slug, v_rev);
    perform public.credit_referral(v_slug);
  end if;
  if v_channel is not null then
    select dr.id into v_run from public.growth_distribution_run dr
      join public.growth_distribution_play pl on pl.id=dr.play_id
     where dr.app=v_app and dr.status='active' and pl.channel=replace(v_channel,'social:','') limit 1;
    insert into public.growth_distribution_metric(run_id, app, channel, signups, cost_usd)
    values (v_run, v_app, v_channel, 1, 0);
  end if;
  return jsonb_build_object('recorded', true, 'app', v_app, 'attributed_to', v_attr, 'run_id', v_run, 'revenue', v_rev);
end $$;

-- (3) EVIDENCE-FIRST: never mint a template task. Intents wait until a real target exists.
create table if not exists public.growth_task_intent (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references public.growth_distribution_run(id) on delete cascade,
  app text not null, kind text not null, template text not null,
  why text, prep jsonb not null default '{}'::jsonb,
  expected_impact numeric not null default 0, effort_minutes int not null default 30,
  needs text,                                   -- what evidence is required to mint it
  status text not null default 'waiting',       -- waiting | minted | dropped
  created_at timestamptz not null default now()
);
alter table public.growth_task_intent enable row level security;

create or replace function public.launch_distribution(p_play_id uuid, p_app text, p_mode text default 'approval')
returns jsonb language plpgsql as $$
declare pl public.growth_distribution_play; run_id uuid; s jsonb; ready int := 0; waiting int := 0; v_title text;
begin
  select * into pl from public.growth_distribution_play where id=p_play_id;
  if not found then raise exception 'play % not found', p_play_id; end if;
  insert into public.growth_distribution_run(play_id, app, mode, status)
  values (p_play_id, p_app, p_mode, 'active') returning id into run_id;
  for s in select * from jsonb_array_elements(coalesce(pl.human_steps,'[]'::jsonb)) loop
    v_title := replace(coalesce(s->>'title_template','Task'), '{app}', p_app);
    if v_title ~ '\{[a-z_]+\}' then
      -- needs a real target: park it as an INTENT, never as a visible task
      insert into public.growth_task_intent(run_id, app, kind, template, why, prep, expected_impact, effort_minutes, needs)
      values (run_id, p_app, coalesce(s->>'kind','write_post'), v_title, s->>'why', coalesce(s->'prep','{}'::jsonb),
              coalesce((s->>'expected_impact')::numeric,0), coalesce((s->>'effort_minutes')::int,30),
              substring(v_title from '\{([a-z_]+)\}'));
      waiting := waiting + 1;
    else
      insert into public.growth_human_task(app, run_id, kind, title, why, prep, expected_impact, effort_minutes, deadline, priority, status)
      values (p_app, run_id, coalesce(s->>'kind','write_post'), v_title, s->>'why', coalesce(s->'prep','{}'::jsonb),
              coalesce((s->>'expected_impact')::numeric,0), coalesce((s->>'effort_minutes')::int,30),
              (now() + make_interval(days => pl.cycle_days))::date,
              case when coalesce((s->>'expected_impact')::numeric,0) > 2000 then 'high' else 'medium' end, 'suggested')
      on conflict (app, kind, target_ref, status) do nothing;
      ready := ready + 1;
    end if;
  end loop;
  return jsonb_build_object('run_id', run_id, 'play', pl.slug, 'app', p_app, 'mode', p_mode,
    'tasks_ready', ready, 'intents_waiting_for_evidence', waiting,
    'agent_steps', jsonb_array_length(coalesce(pl.agent_steps,'[]'::jsonb)),
    'note','Evidence-first: templated asks are intents, never visible tasks. Send gate still governs.');
end $$;

-- (2) CALENDAR: put the chosen minutes into real time blocks.
alter table public.growth_human_task add column if not exists scheduled_for timestamptz;

create or replace function public.schedule_human_week(p_app text default null, p_minutes int default 90, p_start timestamptz default null)
returns jsonb language plpgsql as $$
declare plan jsonb; t jsonb; cursor_ts timestamptz; n int := 0;
begin
  cursor_ts := coalesce(p_start, date_trunc('hour', now()) + interval '1 day' + interval '9 hours');
  plan := public.plan_human_week(p_app, p_minutes);
  for t in select * from jsonb_array_elements(plan->'tasks') loop
    update public.growth_human_task
       set scheduled_for = cursor_ts, status = case when status='suggested' then 'scheduled' else status end
     where id = (t->>'id')::uuid;
    cursor_ts := cursor_ts + make_interval(mins => coalesce((t->>'effort_minutes')::int,30) + 10);
    n := n + 1;
  end loop;
  return jsonb_build_object('scheduled', n, 'first_block', coalesce(p_start, cursor_ts), 'plan', plan);
end $$;

-- (4) DISTRIBUTION-MARKET-FIT TRIAGE: which apps actually have pull.
create or replace function public.distribution_market_fit(p_app text default null)
returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(to_jsonb(x) order by x.signups desc), '[]'::jsonb) from (
    select a.app,
      (select count(*) from public.growth_signup_event e where e.app=a.app) signups,
      (select coalesce(sum(m.cost_usd),0) from public.growth_distribution_metric m where m.app=a.app) spend,
      (select count(*) from public.growth_distribution_run r where r.app=a.app and r.status='active') active_runs,
      (public.distribution_one_number(a.app))->>'signups_per_human_hour' signups_per_human_hour,
      case
        when (select count(*) from public.growth_signup_event e where e.app=a.app) = 0
             and (select count(*) from public.growth_distribution_run r where r.app=a.app and r.status='active') > 0
          then 'no_signal_yet — signup call missing or no pull'
        when (select count(*) from public.growth_signup_event e where e.app=a.app) = 0 then 'not_started'
        when (select coalesce(sum(m.cost_usd),0) from public.growth_distribution_metric m where m.app=a.app)
             / greatest((select count(*) from public.growth_signup_event e where e.app=a.app),1)
             > coalesce((select value::numeric from public.growth_settings where key='distribution_cac_ceiling'),100)
          then 'no_pull — CAC above ceiling, consider stopping'
        else 'pull — keep investing' end verdict
    from (select distinct app from public.growth_channel_account
          union select distinct app from public.growth_distribution_run) a
    where (p_app is null or a.app=p_app)
  ) x;
$$;

insert into public.growth_settings(key,value) values
 ('social_version','v31-referral+evidence-first+marketfit'),
 ('referral_rpcs','issue_referral_link,credit_referral,referral_rollup'),
 ('evidence_first','launch_distribution parks templated asks in growth_task_intent; only evidenced tasks are minted')
on conflict (key) do update set value=excluded.value;;

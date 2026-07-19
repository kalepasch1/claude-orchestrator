-- SIMPLIFY + OPTIMIZE: half-life weighting, the minutes-budget knapsack, self-driving kill/
-- double-down, cold-start for new apps, the one number, and product-as-marketing artifacts.

-- (6) Half-life: durable value beats ephemeral reach.
alter table public.growth_distribution_play add column if not exists half_life_days int not null default 14;
update public.growth_distribution_play set half_life_days = v.hl from (values
  ('reddit-value-answers',30),('show-hn-launch',7),('product-hunt-launch',14),('build-in-public',3),
  ('podcast-circuit',365),('conference-hallway',90),('warm-intro-engine',365),('newsletter-swap',14),
  ('seo-pillar-programmatic',730),('directory-blitz',365),('creator-seeding',30),('referral-loop',180)
) as v(slug,hl) where public.growth_distribution_play.slug = v.slug;

-- Rank by DURABLE value per unit of effort (log-damped half-life), not raw reach.
create or replace function public.recommend_distribution(p_app text default null, p_limit int default 10)
returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(to_jsonb(x) order by x.rank_score desc), '[]'::jsonb) from (
    select p.slug, p.name, p.channel, p.objective, p.cost_usd, p.expected_reach, p.human_minutes,
      p.cycle_days, p.half_life_days, p.score, c.runner, c.cost_level, p.id play_id,
      round(p.expected_reach * (1 + ln(1 + p.half_life_days / 7.0)), 0) durable_reach,
      round(p.score * (p.expected_reach * (1 + ln(1 + p.half_life_days / 7.0)))
            / greatest(p.human_minutes + p.cost_usd, 1), 4) rank_score,
      (select count(*) from public.growth_distribution_run r where r.play_id=p.id and r.app=p_app and r.status='active') already_running
    from public.growth_distribution_play p join public.growth_distribution_channel c on c.channel=p.channel
    where p.status='active' and c.enabled and (p.app_scope='any' or p.app_scope=coalesce(p_app,p.app_scope))
    limit p_limit
  ) x;
$$;

-- (2) ONE SLIDER: give it your weekly minutes; it solves a greedy knapsack over EV/hour.
create or replace function public.plan_human_week(p_app text default null, p_minutes int default 90)
returns jsonb language sql stable as $$
  with ranked as (
    select t.id, t.app, t.kind, t.title, t.why, t.prep, t.target_label, t.target_ref,
           t.effort_minutes, t.expected_impact, t.ev_per_hour, t.deadline,
           sum(t.effort_minutes) over (order by t.ev_per_hour desc, t.id
             rows between unbounded preceding and current row) running
    from public.growth_human_task t
    where t.status in ('suggested','accepted','scheduled') and (p_app is null or t.app=p_app)
  ), chosen as (select * from ranked where running <= p_minutes)
  select jsonb_build_object(
    'budget_minutes', p_minutes,
    'planned_minutes', coalesce((select sum(effort_minutes) from chosen), 0),
    'expected_impact', coalesce((select sum(expected_impact) from chosen), 0),
    'tasks', coalesce((select jsonb_agg(to_jsonb(c) order by c.ev_per_hour desc) from chosen c), '[]'::jsonb));
$$;

-- (3) SELF-DRIVING: pause over-CAC runs, boost proven winners, report one line.
create or replace function public.auto_tune_distribution(p_cac_ceiling numeric default 100)
returns jsonb language plpgsql as $$
declare paused int := 0; boosted int := 0;
begin
  with agg as (
    select r.id, coalesce(sum(m.signups),0) s, coalesce(sum(m.cost_usd),0) c
    from public.growth_distribution_run r left join public.growth_distribution_metric m on m.run_id=r.id
    where r.status='active' group by r.id)
  update public.growth_distribution_run r set status='paused'
    from agg where agg.id=r.id and agg.c > p_cac_ceiling
      and (agg.c / greatest(agg.s,1)) > p_cac_ceiling;
  get diagnostics paused = row_count;

  with agg2 as (
    select r.play_id, coalesce(sum(m.signups),0) s, coalesce(sum(m.cost_usd),0) c
    from public.growth_distribution_run r left join public.growth_distribution_metric m on m.run_id=r.id
    group by r.play_id)
  update public.growth_distribution_play p set score = least(1.0, p.score + 0.05)
    from agg2 where agg2.play_id = p.id and agg2.s >= 3
      and (agg2.c / greatest(agg2.s,1)) < (p_cac_ceiling / 4);
  get diagnostics boosted = row_count;

  return jsonb_build_object('paused', paused, 'boosted', boosted,
    'report', format('Paused %s over-CAC run(s); boosted %s proven winner(s).', paused, boosted));
end $$;

-- (5) COLD START: a new app auto-launches the portfolio's proven plays.
create or replace function public.cold_start_app(p_app text, p_n int default 3, p_mode text default 'approval')
returns jsonb language plpgsql as $$
declare r jsonb; launched int := 0;
begin
  for r in select * from jsonb_array_elements(public.recommend_distribution(p_app, 12)) loop
    exit when launched >= p_n;
    if coalesce((r->>'already_running')::int,0) = 0 then
      perform public.launch_distribution((r->>'play_id')::uuid, p_app, p_mode);
      launched := launched + 1;
    end if;
  end loop;
  return jsonb_build_object('app', p_app, 'launched', launched,
    'note', 'Cold-started from portfolio-proven plays. Human tasks queued as suggestions; send gate still governs.');
end $$;

-- (1)/(7) THE ONE NUMBER: signups per human-hour (plus CAC + revenue).
create or replace function public.distribution_one_number(p_app text default null)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'signups', (select count(*) from public.growth_signup_event e where (p_app is null or e.app=p_app)),
    'revenue', (select round(coalesce(sum(e.revenue),0),2) from public.growth_signup_event e where (p_app is null or e.app=p_app)),
    'human_hours', (select round(coalesce(sum(t.effort_minutes),0)/60.0, 2) from public.growth_human_task t
                     where t.status='done' and (p_app is null or t.app=p_app)),
    'spend', (select round(coalesce(sum(m.cost_usd),0),2) from public.growth_distribution_metric m where (p_app is null or m.app=p_app)),
    'signups_per_human_hour', (
      select round((select count(*) from public.growth_signup_event e where (p_app is null or e.app=p_app))::numeric
        / greatest((select coalesce(sum(t.effort_minutes),0)/60.0 from public.growth_human_task t
                    where t.status='done' and (p_app is null or t.app=p_app)), 1), 2)),
    'cac', (select round((select coalesce(sum(m.cost_usd),0) from public.growth_distribution_metric m where (p_app is null or m.app=p_app))
        / greatest((select count(*) from public.growth_signup_event e where (p_app is null or e.app=p_app)),1), 2))
  );
$$;

-- (7) PRODUCT-AS-MARKETING: real product output becomes distribution material (draft only).
create table if not exists public.growth_proof_artifact (
  id uuid primary key default gen_random_uuid(),
  app text not null,
  kind text not null default 'result',        -- result | metric | prediction | milestone
  headline text not null,
  payload jsonb not null default '{}'::jsonb,
  used boolean not null default false,
  created_at timestamptz not null default now()
);
alter table public.growth_proof_artifact enable row level security;

create or replace function public.record_proof_artifact(p jsonb)
returns jsonb language plpgsql as $$
declare aid uuid; acct uuid; pid uuid;
begin
  insert into public.growth_proof_artifact(app, kind, headline, payload)
  values (coalesce(p->>'app','unknown'), coalesce(p->>'kind','result'), coalesce(p->>'headline','Result'), coalesce(p->'payload','{}'::jsonb))
  returning id into aid;
  -- stage a DRAFT post from the proof (never publishes; send gate + approval still govern)
  select id into acct from public.growth_channel_account
   where app = coalesce(p->>'app','unknown') and status='connected' order by created_at limit 1;
  if acct is not null then
    pid := public.schedule_social_post(jsonb_build_object(
      'app', p->>'app', 'account_id', acct,
      'platform', (select platform from public.growth_channel_account where id=acct),
      'kind','post', 'title', p->>'headline', 'status','draft',
      'meta', jsonb_build_object('needs_generation', true, 'proof_artifact', aid,
              'topic', p->>'headline', 'source','product_output')));
    update public.growth_proof_artifact set used=true where id=aid;
  end if;
  return jsonb_build_object('artifact_id', aid, 'draft_post_id', pid);
end $$;

insert into public.growth_settings(key, value) values
 ('social_version','v30-simplify-optimize'),
 ('distribution_weekly_minutes','90'),
 ('distribution_cac_ceiling','100'),
 ('simplify_rpcs','plan_human_week,auto_tune_distribution,cold_start_app,distribution_one_number,record_proof_artifact')
on conflict (key) do update set value=excluded.value;;

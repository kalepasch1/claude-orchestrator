-- Recommend grassroots plays for an app: proven score x fit x cheapness x low human cost.
create or replace function public.recommend_distribution(p_app text default null, p_limit int default 10)
returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(to_jsonb(x) order by x.rank_score desc), '[]'::jsonb) from (
    select p.slug, p.name, p.channel, p.objective, p.cost_usd, p.expected_reach, p.human_minutes,
      p.cycle_days, p.score, c.runner, c.cost_level, p.id play_id,
      round(p.score * (p.expected_reach::numeric / greatest(p.human_minutes + p.cost_usd, 1)), 4) rank_score,
      (select count(*) from public.growth_distribution_run r where r.play_id=p.id and r.app=p_app and r.status='active') already_running
    from public.growth_distribution_play p join public.growth_distribution_channel c on c.channel=p.channel
    where p.status='active' and c.enabled and (p.app_scope='any' or p.app_scope=coalesce(p_app,p.app_scope))
    limit p_limit
  ) x;
$$;

-- Launch a play for an app: creates the run and materializes its HUMAN tasks (agent steps are
-- executed by the worker). Nothing here sends anything — the send gate still governs all output.
create or replace function public.launch_distribution(p_play_id uuid, p_app text, p_mode text default 'approval')
returns jsonb language plpgsql as $$
declare pl public.growth_distribution_play; run_id uuid; s jsonb; made int := 0;
begin
  select * into pl from public.growth_distribution_play where id=p_play_id;
  if not found then raise exception 'play % not found', p_play_id; end if;
  insert into public.growth_distribution_run(play_id, app, mode, status)
  values (p_play_id, p_app, p_mode, 'active') returning id into run_id;

  for s in select * from jsonb_array_elements(coalesce(pl.human_steps,'[]'::jsonb)) loop
    insert into public.growth_human_task(app, run_id, kind, title, why, prep, expected_impact, effort_minutes, deadline, priority, status)
    values (p_app, run_id, coalesce(s->>'kind','write_post'),
            replace(coalesce(s->>'title_template','Task'), '{app}', p_app),
            s->>'why', coalesce(s->'prep','{}'::jsonb),
            coalesce((s->>'expected_impact')::numeric, 0),
            coalesce((s->>'effort_minutes')::int, 30),
            (now() + make_interval(days => pl.cycle_days))::date,
            case when coalesce((s->>'expected_impact')::numeric,0) > 2000 then 'high' else 'medium' end,
            'suggested')
    on conflict (app, kind, target_ref, status) do nothing;
    made := made + 1;
  end loop;

  return jsonb_build_object('run_id', run_id, 'play', pl.slug, 'app', p_app, 'mode', p_mode,
    'human_tasks', made, 'agent_steps', jsonb_array_length(coalesce(pl.agent_steps,'[]'::jsonb)),
    'note', 'Run active. Agents execute their steps via the worker; human tasks are SUGGESTIONS. Send gate still governs anything that publishes.');
end $$;

-- THE HUMAN QUEUE: only what a human can do, ranked by expected value per hour + deadline urgency.
create or replace function public.rank_human_tasks(p_app text default null, p_limit int default 5)
returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(to_jsonb(x) order by x.urgency desc, x.ev_per_hour desc), '[]'::jsonb) from (
    select t.id, t.app, t.kind, t.title, t.target_label, t.target_ref, t.why, t.prep,
      t.expected_impact, t.effort_minutes, t.ev_per_hour, t.deadline, t.priority, t.status,
      p.name play_name, p.channel,
      round(t.ev_per_hour * case
        when t.deadline is null then 1.0
        when t.deadline <= (now()+interval '2 days')::date then 1.6
        when t.deadline <= (now()+interval '7 days')::date then 1.25
        else 1.0 end, 3) urgency
    from public.growth_human_task t
    left join public.growth_distribution_run r on r.id=t.run_id
    left join public.growth_distribution_play p on p.id=r.play_id
    where t.status in ('suggested','accepted','scheduled') and (p_app is null or t.app=p_app)
    limit p_limit
  ) x;
$$;

-- Human completes/declines a task; the outcome feeds the play's proven score.
create or replace function public.complete_human_task(p_id uuid, p_status text default 'done', p_outcome jsonb default '{}'::jsonb)
returns jsonb language plpgsql as $$
declare t public.growth_human_task; delta numeric;
begin
  update public.growth_human_task set status=p_status, outcome=coalesce(p_outcome,'{}'::jsonb)
   where id=p_id returning * into t;
  if not found then raise exception 'task % not found', p_id; end if;
  if t.run_id is not null then
    delta := case when p_status='done' then 0.03 when p_status='declined' then -0.02 else 0 end;
    update public.growth_distribution_play p set score = greatest(0.05, least(1.0, p.score + delta))
      from public.growth_distribution_run r where r.id=t.run_id and p.id=r.play_id;
    if p_status='done' then
      insert into public.growth_distribution_metric(run_id, app, channel, reach, signups)
      select t.run_id, t.app, p.channel,
             coalesce((p_outcome->>'reach')::int, t.expected_impact::int),
             coalesce((p_outcome->>'signups')::int, 0)
      from public.growth_distribution_run r join public.growth_distribution_play p on p.id=r.play_id
      where r.id=t.run_id;
    end if;
  end if;
  return jsonb_build_object('id', p_id, 'status', p_status);
end $$;

-- Per-channel distribution scoreboard (reach/signups/cost/CAC) for an app or the portfolio.
create or replace function public.distribution_rollup(p_app text default null)
returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(to_jsonb(x) order by x.signups desc nulls last), '[]'::jsonb) from (
    select coalesce(m.channel,'unknown') channel,
      sum(m.reach) reach, sum(m.clicks) clicks, sum(m.signups) signups, round(sum(m.cost_usd),2) cost,
      round(sum(m.cost_usd) / greatest(sum(m.signups),1), 2) cac
    from public.growth_distribution_metric m
    where (p_app is null or m.app=p_app)
    group by 1
  ) x;
$$;

-- Score + iterate: rank runs by measured signups-per-effort, nudge play scores (the agent loop).
create or replace function public.score_distribution_runs()
returns int language plpgsql as $$
declare n int;
begin
  with agg as (
    select r.id run_id, coalesce(sum(m.signups),0) signups, coalesce(sum(m.reach),0) reach, coalesce(sum(m.cost_usd),0) cost
    from public.growth_distribution_run r left join public.growth_distribution_metric m on m.run_id=r.id
    group by r.id)
  update public.growth_distribution_run r
     set outcome_score = round(agg.signups::numeric / greatest(agg.cost + 1, 1), 4),
         metrics = jsonb_build_object('signups',agg.signups,'reach',agg.reach,'cost',agg.cost)
    from agg where agg.run_id = r.id;
  get diagnostics n = row_count;
  -- proven plays drift up, duds drift down
  update public.growth_distribution_play p
     set score = greatest(0.05, least(1.0, p.score + case when x.avg_out > 0.5 then 0.02 when x.avg_out = 0 then -0.01 else 0 end))
    from (select r.play_id, avg(r.outcome_score) avg_out from public.growth_distribution_run r group by r.play_id) x
   where x.play_id = p.id;
  return n;
end $$;

-- One call for the UI: what the agents are doing + what the human must do next.
create or replace function public.distribution_next_actions(p_app text default null)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'send_gate', coalesce((select mode from public.growth_autonomy_switch where scope='send_gate' and key=''),'blocked'),
    'your_tasks', public.rank_human_tasks(p_app, 3),
    'recommended_plays', public.recommend_distribution(p_app, 5),
    'active_runs', (select count(*) from public.growth_distribution_run r where r.status='active' and (p_app is null or r.app=p_app)),
    'open_human_tasks', (select count(*) from public.growth_human_task t where t.status in ('suggested','accepted','scheduled') and (p_app is null or t.app=p_app)),
    'channels', public.distribution_rollup(p_app)
  );
$$;

insert into public.growth_settings(key, value) values
 ('social_version','v28-distribution-engine'),
 ('distribution_rpcs','recommend_distribution,launch_distribution,rank_human_tasks,complete_human_task,distribution_rollup,score_distribution_runs,distribution_next_actions')
on conflict (key) do update set value=excluded.value;;

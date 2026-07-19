-- BUGFIX 1: LIMIT was applied before ORDER BY inside the subqueries, so "top N" returned arbitrary
-- rows. Order INSIDE the subquery, before the limit. Affects the core ranking surfaces.
-- BUGFIX 2: launch_distribution emitted tasks whose titles still contain {placeholders}; those must
-- NOT reach the human queue. They land as 'pending_enrichment' until an agent resolves a real target.

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
    order by rank_score desc
    limit p_limit
  ) x;
$$;

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
    order by urgency desc, t.ev_per_hour desc
    limit p_limit
  ) x;
$$;

create or replace function public.rank_warm_intro_targets(p_app text default null, p_limit int default 10)
returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(to_jsonb(x) order by x.score desc), '[]'::jsonb) from (
    select t.id target_id, t.name target_name, t.company target_company, t.role target_role,
           t.email target_email, t.handle target_handle, t.fit_score,
           c.id connector_id, c.name connector_name, c.email connector_email, c.strength connector_strength,
           ip.path_strength, ip.evidence,
           (select 1.5 from public.growth_social_signal s
             where s.created_at > now() - interval '14 days'
               and (s.author ilike '%'||coalesce(t.handle, t.name, '~none~')||'%')
             limit 1) is not null as has_timing_signal,
           round(c.strength * ip.path_strength * greatest(t.fit_score, 0.3)
                 * coalesce((select 1.5 from public.growth_social_signal s
                              where s.created_at > now() - interval '14 days'
                                and (s.author ilike '%'||coalesce(t.handle, t.name, '~none~')||'%') limit 1), 1.0), 4) score
    from public.growth_intro_path ip
    join public.growth_person t on t.id = ip.target_id
    join public.growth_person c on c.id = ip.connector_id
    where c.strength > 0.25 and t.id <> c.id
      and not exists (
        select 1 from public.growth_human_task h
        where h.kind='call_person' and h.target_ref = coalesce(t.email, t.handle, t.id::text)
          and h.status in ('suggested','accepted','scheduled','done'))
    order by score desc
    limit p_limit
  ) x;
$$;

-- Templates never reach the human: unresolved {placeholders} => 'pending_enrichment'.
create or replace function public.launch_distribution(p_play_id uuid, p_app text, p_mode text default 'approval')
returns jsonb language plpgsql as $$
declare pl public.growth_distribution_play; run_id uuid; s jsonb; made int := 0; pending int := 0;
        v_title text; v_status text;
begin
  select * into pl from public.growth_distribution_play where id=p_play_id;
  if not found then raise exception 'play % not found', p_play_id; end if;
  insert into public.growth_distribution_run(play_id, app, mode, status)
  values (p_play_id, p_app, p_mode, 'active') returning id into run_id;

  for s in select * from jsonb_array_elements(coalesce(pl.human_steps,'[]'::jsonb)) loop
    v_title := replace(coalesce(s->>'title_template','Task'), '{app}', p_app);
    -- if any {placeholder} survives, it needs a real target before a human ever sees it
    v_status := case when v_title ~ '\{[a-z_]+\}' then 'pending_enrichment' else 'suggested' end;
    if v_status = 'pending_enrichment' then pending := pending + 1; else made := made + 1; end if;
    insert into public.growth_human_task(app, run_id, kind, title, why, prep, expected_impact, effort_minutes, deadline, priority, status)
    values (p_app, run_id, coalesce(s->>'kind','write_post'), v_title, s->>'why', coalesce(s->'prep','{}'::jsonb),
            coalesce((s->>'expected_impact')::numeric, 0), coalesce((s->>'effort_minutes')::int, 30),
            (now() + make_interval(days => pl.cycle_days))::date,
            case when coalesce((s->>'expected_impact')::numeric,0) > 2000 then 'high' else 'medium' end,
            v_status)
    on conflict (app, kind, target_ref, status) do nothing;
  end loop;

  return jsonb_build_object('run_id', run_id, 'play', pl.slug, 'app', p_app, 'mode', p_mode,
    'human_tasks_ready', made, 'human_tasks_pending_enrichment', pending,
    'agent_steps', jsonb_array_length(coalesce(pl.agent_steps,'[]'::jsonb)),
    'note', 'Templates stay hidden as pending_enrichment until an agent resolves a real target. Send gate still governs.');
end $$;;

-- NETWORK GRAPH → WARM INTRO ENGINE. Feeds the highest-EV distribution play (warm-intro-engine,
-- score 0.85) with real people + real paths. Idempotent, RLS default-deny.

-- People we've actually touched (ingested from Gmail/calendar/LinkedIn/signals).
create table if not exists public.growth_person (
  id uuid primary key default gen_random_uuid(),
  name text, email text, handle text, company text, role text,
  source text not null default 'gmail',            -- gmail | calendar | linkedin | signal | manual
  first_seen timestamptz not null default now(),
  last_touch timestamptz,
  touch_count int not null default 0,
  inbound_count int not null default 0,
  outbound_count int not null default 0,
  strength numeric not null default 0,              -- 0..1 relationship strength (computed)
  is_icp boolean not null default false,
  fit_score numeric not null default 0,             -- 0..1 ICP fit
  meta jsonb not null default '{}'::jsonb
);
create unique index if not exists idx_person_email on public.growth_person (lower(email)) where email is not null;
create index if not exists idx_person_strength on public.growth_person (strength desc);

-- Candidate warm paths: you -> connector -> target.
create table if not exists public.growth_intro_path (
  id uuid primary key default gen_random_uuid(),
  target_id uuid not null references public.growth_person(id) on delete cascade,
  connector_id uuid not null references public.growth_person(id) on delete cascade,
  path_strength numeric not null default 0.5,       -- confidence connector actually knows target
  evidence jsonb not null default '{}'::jsonb,
  discovered_at timestamptz not null default now(),
  unique (target_id, connector_id)
);

alter table public.growth_person enable row level security;
alter table public.growth_intro_path enable row level security;

-- Relationship strength = recency x frequency x reciprocity (all from real touch data).
create or replace function public.compute_relationship_strength()
returns int language plpgsql as $$
declare n int;
begin
  update public.growth_person p set strength = least(1.0, round((
      0.5 * greatest(0, 1 - (extract(epoch from (now() - coalesce(p.last_touch, p.first_seen))) / 31536000.0))
    + 0.5 * least(1.0, p.touch_count / 20.0)
    ) * (case when p.inbound_count > 0 and p.outbound_count > 0 then 1.0 else 0.6 end), 4));
  get diagnostics n = row_count; return n;
end $$;

-- Rank warm-intro targets: connector strength x path confidence x ICP fit x timing signal.
create or replace function public.rank_warm_intro_targets(p_app text default null, p_limit int default 10)
returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(to_jsonb(x) order by x.score desc), '[]'::jsonb) from (
    select t.id target_id, t.name target_name, t.company target_company, t.role target_role,
           t.email target_email, t.handle target_handle, t.fit_score,
           c.id connector_id, c.name connector_name, c.email connector_email, c.strength connector_strength,
           ip.path_strength, ip.evidence,
           -- timing boost when the target has posted recently (listening signal in the last 14 days)
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
    where c.strength > 0.25                              -- only genuinely warm connectors
      and t.id <> c.id
      and not exists (                                    -- skip targets already queued/handled
        select 1 from public.growth_human_task h
        where h.kind='call_person' and h.target_ref = coalesce(t.email, t.handle, t.id::text)
          and h.status in ('suggested','accepted','scheduled','done'))
    limit p_limit
  ) x;
$$;

-- Materialize the top warm paths into SPECIFIC human tasks (this is the wiring into the queue).
create or replace function public.generate_warm_intro_tasks(p_app text, p_limit int default 3)
returns jsonb language plpgsql as $$
declare r jsonb; made int := 0; run_id uuid; tref text;
begin
  select id into run_id from public.growth_distribution_run dr
   where dr.app = p_app and dr.status='active'
     and dr.play_id = (select id from public.growth_distribution_play where slug='warm-intro-engine')
   limit 1;

  for r in select * from jsonb_array_elements(public.rank_warm_intro_targets(p_app, p_limit)) loop
    tref := coalesce(r->>'target_email', r->>'target_handle', r->>'target_id');
    insert into public.growth_human_task(app, run_id, kind, title, target_label, target_ref, why, prep,
      expected_impact, effort_minutes, deadline, priority, status)
    values (p_app, run_id, 'call_person',
      format('Ask %s for an intro to %s%s', coalesce(r->>'connector_name','your contact'),
             coalesce(r->>'target_name','the target'),
             case when (r->>'target_company') is not null then ' ('||(r->>'target_company')||')' else '' end),
      r->>'target_name', tref,
      format('Warm path: %s is a strong contact (strength %s) who can reach %s%s. Warm intros convert ~10x cold — only you can credibly ask your own contact.%s',
             coalesce(r->>'connector_name','your contact'), coalesce(r->>'connector_strength','0'),
             coalesce(r->>'target_name','them'),
             case when (r->>'target_role') is not null then ' ('||(r->>'target_role')||')' else '' end,
             case when (r->>'has_timing_signal')::boolean then ' They posted publicly in the last 14 days — timely.' else '' end),
      jsonb_build_object(
        'connector', jsonb_build_object('name', r->>'connector_name', 'email', r->>'connector_email'),
        'target', jsonb_build_object('name', r->>'target_name', 'company', r->>'target_company', 'role', r->>'target_role'),
        'ask_draft', format('Hi %s — do you know %s well enough for an intro? Happy to send a forwardable blurb.',
                            split_part(coalesce(r->>'connector_name',''),' ',1), coalesce(r->>'target_name','them')),
        'evidence', r->'evidence',
        'next', 'Agent drafts the forwardable blurb once you say yes.'),
      round(600 * (r->>'score')::numeric, 0), 5, (now() + interval '7 days')::date,
      case when (r->>'score')::numeric > 0.5 then 'high' else 'medium' end, 'suggested')
    on conflict (app, kind, target_ref, status) do nothing;
    made := made + 1;
  end loop;
  return jsonb_build_object('app', p_app, 'tasks_created', made);
end $$;;

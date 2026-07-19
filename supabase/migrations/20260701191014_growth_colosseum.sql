-- 0012_growth_colosseum.sql
create table if not exists growth_strategists (
  id uuid primary key default gen_random_uuid(), handle text unique not null, display_name text not null,
  lens text, objective text not null default 'acquisition', policy jsonb not null default '{}',
  elo numeric(8,2) not null default 1200, calibration numeric(5,4) not null default 0.5000,
  budget_credits numeric(12,2) not null default 100, autonomy numeric(4,3) not null default 0,
  wins int not null default 0, losses int not null default 0, pnl numeric(14,2) not null default 0,
  status text not null default 'active', created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists growth_tournaments (
  id uuid primary key default gen_random_uuid(), objective text not null default 'acquisition',
  target_app text, target_segment text, round int not null default 1, status text not null default 'open',
  baseline_rate numeric(10,6), started_at timestamptz not null default now(), settled_at timestamptz, meta jsonb not null default '{}'
);
create table if not exists growth_proposals (
  id uuid primary key default gen_random_uuid(), tournament_id uuid references growth_tournaments(id) on delete cascade,
  strategist_id uuid references growth_strategists(id) on delete set null, hypothesis text, predicted_lift numeric(8,4) default 0,
  rationale text, arm_id uuid references growth_arms(id) on delete set null, critique_score numeric(5,2),
  allocation numeric(6,4) not null default 0, status text not null default 'submitted', realized_lift numeric(8,4),
  created_at timestamptz not null default now()
);
create index if not exists growth_proposals_tourn_idx on growth_proposals (tournament_id, status);
create table if not exists growth_strategist_scores (
  id bigint generated always as identity primary key, strategist_id uuid references growth_strategists(id) on delete cascade,
  proposal_id uuid references growth_proposals(id) on delete cascade, predicted_lift numeric(8,4), realized_lift numeric(8,4),
  brier numeric(6,4), pnl numeric(14,2), created_at timestamptz not null default now()
);

create or replace function open_tournament(p_objective text, p_app text, p_segment_path text)
returns uuid language plpgsql as $$
declare tid uuid; seg uuid; base numeric;
begin
  select id into seg from growth_segments where path = p_segment_path;
  select case when sum(impressions)>0 then sum(conversions)::numeric/sum(impressions) else 0 end into base from growth_arms where segment_id = seg;
  insert into growth_tournaments(objective, target_app, target_segment, baseline_rate, meta)
  values (p_objective, p_app, p_segment_path, coalesce(base,0), jsonb_build_object('segment_id', seg)) returning id into tid;
  return tid;
end $$;

create or replace function allocate_tournament(p_tournament_id uuid, p_keep int default 4)
returns int language plpgsql as $$
declare n int := 0;
begin
  with ranked as (
    select pr.id, s.elo*(1+greatest(pr.predicted_lift,0))*(0.5+coalesce(pr.critique_score,50)/100.0) as w,
      row_number() over (order by s.elo*(1+greatest(pr.predicted_lift,0)) desc) as rnk
    from growth_proposals pr join growth_strategists s on s.id = pr.strategist_id
    where pr.tournament_id = p_tournament_id and pr.status='submitted'
  ),
  kept as (select id, w from ranked where rnk <= p_keep),
  tot as (select sum(w) sw from kept)
  update growth_proposals pr
    set allocation = case when pr.id in (select id from kept) then round((select w from kept where kept.id=pr.id)/nullif((select sw from tot),0),4) else 0 end,
        status = case when pr.id in (select id from kept) then 'live' else 'cut' end
  where pr.tournament_id = p_tournament_id and pr.status='submitted';
  get diagnostics n = row_count;
  update growth_tournaments set status='running' where id=p_tournament_id;
  return n;
end $$;

create or replace function settle_tournament(p_tournament_id uuid, p_min_impressions bigint default 100)
returns uuid language plpgsql as $$
declare t growth_tournaments; field_avg numeric; rec record; winner uuid; best numeric := -1e9;
  v_rate numeric; v_lift numeric; v_actual numeric; v_expected numeric; v_brier numeric; v_np numeric; v_nr numeric; play uuid;
begin
  select * into t from growth_tournaments where id = p_tournament_id;
  select avg(s.elo) into field_avg from growth_proposals pr join growth_strategists s on s.id=pr.strategist_id
    where pr.tournament_id=p_tournament_id and pr.status='live';
  field_avg := coalesce(field_avg, 1200);
  for rec in
    select pr.id as pid, pr.predicted_lift, pr.strategist_id, a.id as arm_id, a.impressions, a.conversions,
           a.reward_sum, s.elo, s.calibration
    from growth_proposals pr join growth_arms a on a.id = pr.arm_id join growth_strategists s on s.id = pr.strategist_id
    where pr.tournament_id = p_tournament_id and pr.status='live'
  loop
    if rec.impressions < p_min_impressions then continue; end if;
    v_rate := case when rec.impressions>0 then rec.conversions::numeric/rec.impressions else 0 end;
    v_lift := case when coalesce(t.baseline_rate,0)>0 then (v_rate - t.baseline_rate)/t.baseline_rate else 0 end;
    v_lift := least(3, greatest(-1, v_lift));
    v_actual := case when v_lift > 0 then 1 else 0 end;
    v_expected := 1.0/(1.0 + power(10, (field_avg - rec.elo)/400.0));
    v_np := least(1,greatest(0,(coalesce(rec.predicted_lift,0)+1)/4.0));
    v_nr := least(1,greatest(0,(v_lift+1)/4.0));
    v_brier := power(v_np - v_nr, 2);
    update growth_strategists set
      elo = elo + 24*(v_actual - v_expected),
      calibration = round(0.7*calibration + 0.3*(1 - v_brier), 4),
      wins = wins + (case when v_actual=1 then 1 else 0 end),
      losses = losses + (case when v_actual=0 then 1 else 0 end),
      pnl = pnl + coalesce(rec.reward_sum,0),
      budget_credits = greatest(0, budget_credits + 10*(v_actual - v_expected)), updated_at = now()
    where id = rec.strategist_id;
    update growth_strategists set autonomy = least(1, greatest(0, ((elo-1200)/600.0)*0.5 + calibration*0.5)) where id = rec.strategist_id;
    insert into growth_strategist_scores(strategist_id, proposal_id, predicted_lift, realized_lift, brier, pnl)
    values (rec.strategist_id, rec.pid, rec.predicted_lift, v_lift, v_brier, coalesce(rec.reward_sum,0));
    update growth_proposals set realized_lift = v_lift, status='settled' where id = rec.pid;
    if v_lift > best then best := v_lift; winner := rec.pid; end if;
  end loop;
  if winner is not null and best > 0 then
    select promote_arm_to_play(pr.arm_id, 'colosseum:'||t.target_app||':'||to_char(now(),'YYYY-MM-DD')||':'||left(pr.id::text,8), 'creative')
      into play from growth_proposals pr where pr.id = winner;
  end if;
  update growth_tournaments set status='settled', settled_at=now(),
    meta = meta || jsonb_build_object('winner_proposal', winner, 'winning_lift', best, 'play', play) where id = p_tournament_id;
  return winner;
end $$;

do $$
declare tbl text;
begin
  foreach tbl in array array['growth_strategists','growth_tournaments','growth_proposals','growth_strategist_scores'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function open_tournament(text,text,text) to authenticated, service_role;
grant execute on function allocate_tournament(uuid,int) to authenticated, service_role;
grant execute on function settle_tournament(uuid,bigint) to authenticated, service_role;

create or replace view growth_leaderboard as
select handle, display_name, lens, objective, elo, calibration, wins, losses, round(pnl,0) pnl, round(autonomy,3) autonomy, budget_credits, status
from growth_strategists order by elo desc;

insert into growth_strategists (handle, display_name, lens, objective, policy) values
 ('ogilvy','David Ogilvy','Research-led credibility, long copy, big idea','acquisition','{"voice":"authoritative, factual, benefit-led"}'),
 ('bernbach','Bill Bernbach','Creative disruption, emotion, wit','acquisition','{"voice":"bold, unexpected, human"}'),
 ('hopkins','Claude Hopkins','Scientific advertising, reason-why, relentless testing','acquisition','{"voice":"specific, proof-driven"}'),
 ('halbert','Gary Halbert','Direct-response, story, urgency','acquisition','{"voice":"punchy, personal"}'),
 ('kennedy','Dan Kennedy','Offer engineering, deadlines, risk reversal','monetization','{"voice":"offer-first, urgent"}'),
 ('godin','Seth Godin','Remarkable, permission, tribes','acquisition','{"voice":"concise, contrarian"}'),
 ('sinek','Simon Sinek','Purpose / start-with-why','acquisition','{"voice":"purpose-driven"}'),
 ('cialdini','Robert Cialdini','7 persuasion principles as levers','activation','{"voice":"principle-tagged"}'),
 ('ries-trout','Ries & Trout','Positioning & category design','acquisition','{"voice":"category-defining"}'),
 ('sharp','Byron Sharp','Mental & physical availability, reach, distinctive assets','acquisition','{"voice":"broad-reach, brand codes"}'),
 ('brunson','Russell Brunson','Value ladder & funnels','monetization','{"voice":"funnel-staged"}'),
 ('plg','PLG (Ellis/Chen)','Activation loops & viral coefficient','activation','{"voice":"product-led, loop-focused"}'),
 ('community','Community-led','Advocacy, word-of-mouth, belonging','retention','{"voice":"member-first"}'),
 ('guerrilla','Guerrilla Wildcard','Unconventional, high-surprise mechanisms','acquisition','{"voice":"scrappy, novel"}'),
 ('superintel','Superintelligence','AI-native tactics beyond human playbooks','acquisition','{"voice":"novel, data-native"}')
on conflict (handle) do nothing;

insert into loops (project, type, cadence_seconds, config)
values ('claude-orchestrator','colosseum', 3600, '{"loop":"colosseum","top_keep":4,"min_impressions":100}')
on conflict (project, type) do nothing;;

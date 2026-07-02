-- 0014_growth_bd_autopilot.sql
-- Autonomous BD/CRM: cross-bot playbook LEARNING (shared by every app's bots), a contact-level
-- outreach state machine, and a low-involvement HUMAN QUEUE (only meetings, presentations, and
-- flagged email material reach the human — everything else runs autonomously). Idempotent.

-- Cross-bot learned playbooks: any bot that runs a sequence updates the SHARED row, so a win in one
-- app instantly improves every bot's outreach for that segment/channel. This is the real-time,
-- across-all-bots learning loop.
create table if not exists growth_bd_playbook (
  id         uuid primary key default gen_random_uuid(),
  segment    text,                       -- growth_segments.path (nullable = default)
  channel    text not null default 'email',
  sequence   jsonb not null default '[]',-- [{step, channel, template_key, wait_hours, goal}]
  sends      bigint not null default 0,
  replies    bigint not null default 0,
  meetings   bigint not null default 0,
  wins       bigint not null default 0,
  reward     numeric(14,2) not null default 0,
  score      numeric(10,4) not null default 0,  -- learned quality (recomputed on each outcome)
  status     text not null default 'active',
  updated_at timestamptz not null default now(),
  unique (segment, channel)
);

-- Pick the best-learned sequence for a segment (fall back to channel default, then any).
create or replace function bd_pick_sequence(p_segment text, p_channel text default 'email')
returns growth_bd_playbook language plpgsql stable as $$
declare pb growth_bd_playbook;
begin
  select * into pb from growth_bd_playbook
    where status='active' and (segment = p_segment) and channel = p_channel order by score desc limit 1;
  if found then return pb; end if;
  select * into pb from growth_bd_playbook
    where status='active' and segment is null and channel = p_channel order by score desc limit 1;
  if found then return pb; end if;
  select * into pb from growth_bd_playbook where status='active' order by score desc limit 1;
  return pb;
end $$;

-- Cross-bot learning: fold an outcome into the shared playbook + recompute score.
create or replace function bd_learn(p_playbook_id uuid, p_outcome text, p_value numeric default 0)
returns void language plpgsql as $$
begin
  update growth_bd_playbook set
    sends    = sends    + (case when p_outcome in ('send','sent') then 1 else 0 end),
    replies  = replies  + (case when p_outcome='reply' then 1 else 0 end),
    meetings = meetings + (case when p_outcome='meeting' then 1 else 0 end),
    wins     = wins     + (case when p_outcome='win' then 1 else 0 end),
    reward   = reward   + coalesce(p_value,0),
    updated_at = now()
  where id = p_playbook_id;
  -- score = weighted outcomes per send (reply=1, meeting=4, win=12), + small reward signal
  update growth_bd_playbook set
    score = round((replies + 4*meetings + 12*wins)::numeric / greatest(sends,1)
                  + ln(1+reward)/50.0, 4)
  where id = p_playbook_id;
end $$;

-- Contact-level autonomous outreach state machine (actor hashed — no PII).
create table if not exists growth_outreach (
  id           uuid primary key default gen_random_uuid(),
  app          text not null,
  actor_hash   text,
  segment      text,
  playbook_id  uuid references growth_bd_playbook(id) on delete set null,
  step         int not null default 0,
  state        text not null default 'queued',  -- queued|sent|awaiting|replied|meeting_set|won|lost|human_needed
  next_action_at timestamptz not null default now(),
  last_channel text,
  meta         jsonb not null default '{}',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists growth_outreach_due_idx on growth_outreach (state, next_action_at);

-- Low-involvement human queue. The bot PREPARES everything; the human only does the irreducible bit.
create table if not exists growth_human_queue (
  id          uuid primary key default gen_random_uuid(),
  app         text not null,
  kind        text not null,                 -- meeting | presentation | email_material | approval
  actor_hash  text,
  segment     text,
  title       text not null,
  why         text,                          -- why the human is needed (bot's reasoning)
  prepared    jsonb not null default '{}',    -- bot-prepared material: draft, brief, proposed_times, deck_outline
  status      text not null default 'open',   -- open | scheduled | done | dismissed
  created_at  timestamptz not null default now(),
  resolved_at timestamptz
);
create index if not exists growth_human_queue_status_idx on growth_human_queue (status, created_at desc);

-- Escalate to the human ONLY when unavoidable; carry the prepared material so effort is minimal.
create or replace function bd_escalate(p_app text, p_kind text, p_title text, p_why text,
  p_prepared jsonb default '{}', p_actor_hash text default null, p_segment text default null)
returns uuid language plpgsql as $$
declare qid uuid;
begin
  insert into growth_human_queue(app, kind, title, why, prepared, actor_hash, segment)
  values (p_app, p_kind, p_title, p_why, coalesce(p_prepared,'{}'), p_actor_hash, p_segment)
  returning id into qid;
  return qid;
end $$;

-- Extend the Smarter action feed to include the human queue (meetings/presentations/flagged material).
create or replace view growth_action_feed as
select 'task'::text as item_kind, t.id::text as item_id, p.name as app, t.slug as title,
       t.state::text as status, t.note as detail, t.created_at
from tasks t join projects p on p.id = t.project_id
where t.kind='gtm' and t.state in ('QUEUED','WAITING','BLOCKED','RETRY')
union all
select 'approval'::text, a.id::text, a.project, a.title, a.status::text, a.why, a.created_at
from approvals a where a.status='pending' and (a.kind in ('gtm','proposal','material'))
union all
select 'human:'||h.kind, h.id::text, h.app, h.title, h.status, h.why, h.created_at
from growth_human_queue h where h.status='open'
order by created_at desc;

-- ---------------- RLS + grants ----------------
do $$
declare tbl text;
begin
  foreach tbl in array array['growth_bd_playbook','growth_outreach','growth_human_queue'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function bd_pick_sequence(text,text) to authenticated, service_role;
grant execute on function bd_learn(uuid,text,numeric) to authenticated, service_role;
grant execute on function bd_escalate(text,text,text,text,jsonb,text,text) to authenticated, service_role;

-- Seed a sensible default outreach sequence so bots have something to run + learn from.
insert into growth_bd_playbook (segment, channel, sequence, status) values
 (null, 'email',
  '[{"step":1,"channel":"email","template_key":"intro_value","wait_hours":0,"goal":"open_reply"},
    {"step":2,"channel":"email","template_key":"proof_case_study","wait_hours":72,"goal":"reply"},
    {"step":3,"channel":"email","template_key":"soft_meeting_ask","wait_hours":96,"goal":"meeting"},
    {"step":4,"channel":"email","template_key":"breakup_offer","wait_hours":120,"goal":"meeting"}]'::jsonb,
  'active')
on conflict (segment, channel) do nothing;

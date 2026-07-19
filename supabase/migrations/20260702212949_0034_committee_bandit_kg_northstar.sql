-- multi-armed portfolio bandit state (per app)
create table if not exists board_bandit (
  app text primary key, pulls integer default 0, reward_sum numeric default 0,
  avg_reward numeric default 0, updated_at timestamptz default now()
);

-- cross-committee knowledge graph: linked opinions/precedents/dissents/outcomes
create table if not exists kg_edges (
  id uuid primary key default gen_random_uuid(),
  from_kind text, from_key text, to_kind text, to_key text,
  relation text, weight numeric default 1, created_at timestamptz default now()
);
create index if not exists idx_kg_from on kg_edges(from_key);

-- meta-committee: proposed/applied changes to the committee SYSTEM itself
create table if not exists committee_charter (
  id uuid primary key default gen_random_uuid(),
  change text, committee text, rationale text, applied boolean default false,
  created_at timestamptz default now()
);

-- owner north-star goals used to score every autonomous decision for alignment/drift
create table if not exists owner_goals (
  id uuid primary key default gen_random_uuid(),
  goal text, weight numeric default 1, active boolean default true
);

alter table committee_actions add column if not exists alignment numeric;

insert into owner_goals (goal, weight) values
  ('Maximize value per compute dollar; keep real API spend at $0 on subscription', 1.5),
  ('Ship real, tested improvements to production continuously — no credit-burn loops', 1.4),
  ('Operate autonomously; only escalate critical or highly contentious decisions', 1.3),
  ('Grow the portfolio (users, MRR) without diverging the core business model unapproved', 1.2),
  ('Preserve trust, safety, legal compliance, and user privacy', 1.5)
on conflict do nothing;;

-- a CADE Determination: the engine's answer to one contestable unit, with contributors, factions,
-- consensus %, an Optimality Certificate, and a hash-chained proof.
create table if not exists determinations (
  id uuid primary key default gen_random_uuid(),
  subject_type text, subject_id uuid, title text,
  position text, recommendation text,
  consensus_pct numeric, confidence numeric, materiality numeric,
  contributors jsonb, factions jsonb, dissent jsonb,
  certificate jsonb, proof_hash text, prev_hash text,
  onepager text, created_at timestamptz default now()
);
create index if not exists idx_determ_subject on determinations(subject_type, subject_id);

-- calibratable consensus floor: below this, the 1-pager flags contention for the reviewer's attention
insert into owner_model (key, value) values ('consensus_floor', 0.85)
on conflict (key) do nothing;;

-- weekly owner digest of the sharpest dissents / reversals / low-confidence calls
create table if not exists committee_digests (
  id uuid primary key default gen_random_uuid(),
  period text, headline text, body text, created_at timestamptz default now()
);

-- continuous docket: track when a shipped feature was last re-reviewed by committees
create table if not exists committee_docket (
  subject_key text primary key,      -- e.g. app:slug
  app text, slug text,
  last_verdict text, last_reviewed_at timestamptz default now()
);

-- record every autonomous action a committee took (so the owner can audit what ran without them)
create table if not exists committee_actions (
  id uuid primary key default gen_random_uuid(),
  subject_type text, subject_id uuid, subject_title text,
  action text, recommendation text, aggregate numeric, conviction numeric,
  critical boolean default false, created_at timestamptz default now()
);

-- forecast + criticality captured on each opinion
alter table committee_opinions add column if not exists p_success numeric;
alter table committee_opinions add column if not exists expected_value numeric;;

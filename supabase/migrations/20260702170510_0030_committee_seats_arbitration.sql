-- per-SEAT verdict trail (so we can score individual experts, not just committees)
create table if not exists committee_seat_reviews (
  id uuid primary key default gen_random_uuid(),
  subject_type text, subject_id uuid, committee text, seat text,
  verdict text, score numeric, conviction numeric,
  outcome numeric, created_at timestamptz default now()
);
create index if not exists idx_csr on committee_seat_reviews(committee, seat);

-- learned reliability weight per seat (from backtesting outcomes)
create table if not exists seat_calibration (
  committee text, seat text, n integer, accuracy numeric, weight numeric,
  updated_at timestamptz default now(),
  primary key (committee, seat)
);

-- record of cross-committee arbitrations (deadlock tiebreaks)
create table if not exists committee_arbitrations (
  id uuid primary key default gen_random_uuid(),
  subject_type text, subject_id uuid, subject_title text,
  parties text, ruling text, rationale text, created_at timestamptz default now()
);

-- flag when a new opinion contradicts an established precedent
alter table committee_opinions add column if not exists precedent_conflict text;;

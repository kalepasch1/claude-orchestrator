-- consensus distribution (CI), pivotal-factor sensitivity, adversarial discount, consistency, vindication
alter table determinations add column if not exists consensus_lo numeric;
alter table determinations add column if not exists consensus_hi numeric;
alter table determinations add column if not exists pivotal jsonb;          -- {expert, would_flip_to}
alter table determinations add column if not exists adv_discount numeric;   -- 0..1 confidence haircut from red-team
alter table determinations add column if not exists consistency_flag text;  -- contradicts prior precedent
alter table determinations add column if not exists dissent_vindicated boolean default false;

-- per-reviewer / per-domain contention routing floors (fallback to owner_model.consensus_floor)
create table if not exists reviewer_prefs (
  reviewer text, domain text, consensus_floor numeric,
  updated_at timestamptz default now(),
  primary key (reviewer, domain)
);;

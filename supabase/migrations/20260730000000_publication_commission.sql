-- Publication Commission: the editorial gate over Consilium output.
-- Volume is not value. Every candidate artifact is scored by an adversarial panel of reviewers
-- (rigor / evidence / novelty / utility / exposure) before it may be published OR used to steer.
-- The score is a first-class platform signal, not just a record: publication, Foulkon steering,
-- advisory citation, and risk-score confidence all read from it.

create table if not exists public.publication_reviews (
  id            uuid primary key default gen_random_uuid(),
  artifact_id   text not null,
  artifact_type text not null default 'committee_opinion',
  composite     numeric(5,4) not null,
  decision      text not null check (decision in ('publish','steer_only','revise','reject')),
  detail        jsonb not null default '{}'::jsonb,   -- per-reviewer scores + rationales + veto
  -- calibration: filled in later when reality answers back (did the published position hold?)
  outcome       text,
  outcome_at    timestamptz,
  created_at    timestamptz not null default now(),
  unique (artifact_id, artifact_type)
);

create index if not exists publication_reviews_decision_idx
  on public.publication_reviews(decision, created_at desc);
create index if not exists publication_reviews_composite_idx
  on public.publication_reviews(composite desc);

alter table public.publication_reviews enable row level security;

-- Read-only for authenticated surfaces (dashboards, advisory citation checks); writes are
-- service-role only (the commission itself).
do $$ begin
  execute 'drop policy if exists publication_reviews_read on public.publication_reviews';
  execute 'create policy publication_reviews_read on public.publication_reviews
             for select to authenticated using (true)';
end $$;

select 'publication_commission migration OK' as status;

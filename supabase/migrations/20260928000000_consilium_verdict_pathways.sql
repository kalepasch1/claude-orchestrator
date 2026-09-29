-- Consilium structuring tribunal (2026-09-28): ranked LAWFUL pathways per objective.
-- A verdict card answers "is X lawful and what flips it". A pathway run answers the question the
-- operator actually asks next: "given that, what are the lawful routes to the objective, where is
-- the regime weakest, how do jurisdictions differ, and what would make us abandon each route".
-- Every pathway is attacked by an enforcement red team before it is ranked, carries an explicit
-- risk posture, and is review-only until an attorney adopts it.
-- Applied to project eatfwdzfurujcuwlhdgj (claude-orchestrator) on 2026-09-28.

create table if not exists public.pathway_runs (
  id                  uuid primary key default gen_random_uuid(),
  card_id             uuid references public.verdict_cards(id) on delete set null,
  docket_id           uuid,
  vertical            text not null,
  objective           text not null,
  regime_map          jsonb not null default '[]'::jsonb,
  weak_points         jsonb not null default '[]'::jsonb,
  jurisdiction_matrix jsonb not null default '[]'::jsonb,
  opportunities       jsonb not null default '[]'::jsonb,
  summary             text,
  citations_total     int not null default 0,
  citations_verified  int not null default 0,
  process             jsonb not null default '{}'::jsonb,
  created_at          timestamptz not null default now()
);

create table if not exists public.verdict_pathways (
  id                      uuid primary key default gen_random_uuid(),
  run_id                  uuid not null references public.pathway_runs(id) on delete cascade,
  card_id                 uuid references public.verdict_cards(id) on delete set null,
  vertical                text not null,
  rank                    int not null,
  title                   text not null,
  kind                    text not null check (kind in (
                            'licensing_pathway','structural_redesign','jurisdictional_sequencing',
                            'partner_or_sponsor','exemption_or_safe_harbor','regulatory_engagement',
                            'product_boundary','other')),
  structure               text not null,
  legal_theory            text not null,
  jurisdictions           jsonb not null default '[]'::jsonb,
  citations               jsonb not null default '[]'::jsonb,
  retained                jsonb not null default '[]'::jsonb,
  lost                    jsonb not null default '[]'::jsonb,
  time_to_market_days     int,
  cost_band               text,
  value_band              text,
  risk_posture            text not null check (risk_posture in ('conservative','defensible','aggressive_arguable')),
  durability              numeric(4,3),
  enforcement_probability numeric(4,3),
  substance_over_form     text,
  red_team                jsonb not null default '{}'::jsonb,
  kill_criteria           text,
  first_steps             jsonb not null default '[]'::jsonb,
  score                   numeric(5,4),
  status                  text not null default 'proposed' check (status in (
                            'proposed','attorney_review','adopted','rejected','stale')),
  created_at              timestamptz not null default now(),
  unique (run_id, rank)
);

create index if not exists verdict_pathways_vertical_idx on public.verdict_pathways(vertical, status, score desc);
create index if not exists verdict_pathways_card_idx on public.verdict_pathways(card_id);
create index if not exists pathway_runs_card_idx on public.pathway_runs(card_id);
create index if not exists pathway_runs_created_idx on public.pathway_runs(created_at desc);

alter table public.pathway_runs enable row level security;
alter table public.verdict_pathways enable row level security;

do $$ begin
  execute 'drop policy if exists pathway_runs_read on public.pathway_runs';
  execute 'create policy pathway_runs_read on public.pathway_runs for select to authenticated using (true)';
  execute 'drop policy if exists verdict_pathways_read on public.verdict_pathways';
  execute 'create policy verdict_pathways_read on public.verdict_pathways for select to authenticated using (true)';
end $$;

select 'consilium_verdict_pathways migration OK' as status;

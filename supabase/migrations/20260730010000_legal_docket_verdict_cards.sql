-- Legal docket + verdict cards: point the Consilium at LAW, and pre-compute its answers.
--
-- Context: the Consilium had only ever been fed `improvement_proposals` (our own engineering
-- backlog), so panels named "Legal & Compliance" were opining on Kubernetes. This gives it a
-- standing docket of real regulatory questions per vertical, and stores each answer as a
-- pre-computed, citation-backed VERDICT CARD that Foulkon can look up in milliseconds at
-- code/decision time instead of convening a panel (which would gate the build).

create table if not exists public.legal_docket (
  id         uuid primary key default gen_random_uuid(),
  vertical   text not null,                     -- gaming | finserv | aidata | ...
  question   text not null,
  priority   text not null default 'medium' check (priority in ('high','medium','low')),
  status     text not null default 'pending' check (status in ('pending','answered','stale','retired')),
  created_at timestamptz not null default now(),
  unique (vertical, question)
);
create index if not exists legal_docket_status_idx on public.legal_docket(status, priority);

create table if not exists public.verdict_cards (
  id              uuid primary key default gen_random_uuid(),
  docket_id       uuid references public.legal_docket(id) on delete cascade,
  vertical        text not null,
  question        text not null,
  position        text not null,                -- the memo-grade analysis
  verdict         text,
  confidence      numeric(4,3),
  citations       jsonb not null default '[]'::jsonb,
  assumptions     jsonb not null default '[]'::jsonb,
  dissent         text,
  authority_chain jsonb not null default '[]'::jsonb,  -- staleness is computed off this
  minted_at       timestamptz not null default now(),
  status          text not null default 'fresh' check (status in ('fresh','stale','superseded')),
  unique (docket_id)
);
create index if not exists verdict_cards_lookup_idx on public.verdict_cards(vertical, status);
-- authority-chain GIN index: when a rule/case changes, find exactly the cards it invalidates.
create index if not exists verdict_cards_authority_idx on public.verdict_cards using gin (authority_chain);

-- committee_opinions gains structured evidence (previously the analysis had nowhere to put cites)
alter table public.committee_opinions add column if not exists citations  jsonb default '[]'::jsonb;
alter table public.committee_opinions add column if not exists assumptions jsonb default '[]'::jsonb;

alter table public.legal_docket  enable row level security;
alter table public.verdict_cards enable row level security;
do $$ begin
  execute 'drop policy if exists legal_docket_read on public.legal_docket';
  execute 'create policy legal_docket_read on public.legal_docket for select to authenticated using (true)';
  execute 'drop policy if exists verdict_cards_read on public.verdict_cards';
  execute 'create policy verdict_cards_read on public.verdict_cards for select to authenticated using (true)';
end $$;

select 'legal_docket + verdict_cards migration OK' as status;

-- Expert insights (2026-09-21). Additive only.
--
-- 1. legal_docket gains the coordinates of the question matrix: WHICH lens the question
--    looks through, WHERE on the risk spectrum it sits, and WHO generated it. A week of
--    free-form generation produced 1,874 questions of which 55% were "high", six gaming
--    personas dominated, 2.6% had any innovation or cross-industry framing and the data
--    vertical was never reached. Coverage can only be balanced if it can be counted.
-- 2. steering_insights is where a verdict card stops being a document and becomes
--    steering: one row per imperative the card implies (an action, a tripwire, a
--    regulatory gap, an innovation pathway, an opportunity). Until now only two modules
--    ever read verdict_cards, so the corps' work steered nothing.
--
-- Internal work product throughout: publication_state defaults to 'internal'.

alter table public.legal_docket add column if not exists lens      text;
alter table public.legal_docket add column if not exists risk_band text;
alter table public.legal_docket add column if not exists origin    text;
create index if not exists legal_docket_matrix_idx on public.legal_docket(vertical, lens, risk_band);

create table if not exists public.steering_insights (
  id                uuid primary key default gen_random_uuid(),
  card_id           uuid references public.verdict_cards(id) on delete cascade,
  docket_id         uuid,
  vertical          text not null,
  kind              text not null check (kind in ('action','tripwire','gap','innovation','opportunity','assumption')),
  lens              text,
  risk_band         text,
  insight           text not null,                       -- one imperative sentence
  rationale         text,                                -- the card text it was distilled from
  terms             text[] not null default '{}',        -- salient terms, for matching a task to an insight
  confidence        numeric(4,3),
  signature         text not null,                       -- normalised content hash, for dedup
  status            text not null default 'active' check (status in ('active','superseded','retired')),
  publication_state text not null default 'internal',
  served_count      int  not null default 0,
  created_at        timestamptz not null default now(),
  unique (card_id, signature)
);
create index if not exists steering_insights_vertical_idx on public.steering_insights(vertical, status);
create index if not exists steering_insights_kind_idx     on public.steering_insights(kind, status);
create index if not exists steering_insights_terms_idx    on public.steering_insights using gin(terms);

alter table public.steering_insights enable row level security;

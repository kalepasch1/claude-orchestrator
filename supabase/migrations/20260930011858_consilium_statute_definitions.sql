-- statute_definitions: each jurisdiction's own statutory definitions, verbatim, looked up instead of re-researched.
--
-- WHY (2026-09-29, operator-approved). Doctrine-selector questions -- which chance/skill test a state applies,
-- what counts as a lottery, a regulated game promotion, money transmission -- are answered first by the
-- jurisdiction's statute. The question-family pass was re-finding those sections by case-law search and web
-- research on every run, and missing them where the free sources had none. This table holds the verbatim
-- text once, with its URL, so a cell becomes a lookup.
--
-- FILLED FOR FREE. statute_kb.py copies statute passages from the corpus (jurisdiction-scoped full-text
-- search) and records the official statute pages the family pass adopts through its capped, fetch-verified
-- web research. Nothing is paraphrased: `text` is the source's own words and `text_sha` identifies it.
-- Service-role only.

create table if not exists public.statute_definitions (
  id          uuid primary key default gen_random_uuid(),
  jurisdiction text not null,                          -- 'US-OH', or a tribal / territorial code
  topic       text not null check (topic in ('gambling', 'lottery', 'sweepstakes', 'money_transmission', 'skill_contest')),
  citation    text not null,
  heading     text,
  url         text not null,
  text        text not null,
  text_sha    text not null,
  source      text not null default 'corpus' check (source in ('corpus', 'official_web', 'web_research')),
  doc_id      text,
  fetched_at  timestamptz not null default now(),
  unique (jurisdiction, topic, text_sha)
);

create index if not exists statute_definitions_lookup_idx on public.statute_definitions (jurisdiction, topic);

alter table public.statute_definitions enable row level security;

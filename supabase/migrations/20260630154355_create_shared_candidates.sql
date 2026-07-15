create table if not exists public.shared_candidates (
  id bigint generated always as identity primary key,
  key text unique not null,
  domain text,
  what text,
  project text,
  slug text,
  kind text,
  projects text[] default '{}',
  occurrences int default 1,
  proposed boolean default false,
  seen_at timestamptz default now(),
  last_seen timestamptz default now(),
  created_at timestamptz default now()
);
create index if not exists shared_candidates_proposed_idx on public.shared_candidates (proposed);
create index if not exists shared_candidates_occurrences_idx on public.shared_candidates (occurrences desc);;

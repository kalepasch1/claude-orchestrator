create table if not exists merged_diffs (
  id uuid primary key default gen_random_uuid(),
  project text,
  slug text,
  kind text,
  prompt text,
  diff text,
  files jsonb,
  words jsonb,
  symbols jsonb,
  tests jsonb,
  frameworks jsonb,
  acceptance text,
  created_at timestamptz default now()
);

create unique index if not exists merged_diffs_project_slug_unique
  on merged_diffs(project, slug);

create table if not exists verifier_outcomes (
  id uuid primary key default gen_random_uuid(),
  provider text,
  model text,
  verdict text,
  integrated boolean default false,
  deployed boolean default false,
  created_at timestamptz default now()
);;

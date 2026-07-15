-- The 8 growth-loop features. All idempotent, RLS default-deny.

-- (1) Metrics + bandit experiments -------------------------------------------------
alter table public.growth_social_post add column if not exists variant_id uuid;
alter table public.growth_social_post add column if not exists tracked_slug text;
create table if not exists public.growth_social_experiment (
  id uuid primary key default gen_random_uuid(),
  app text not null default 'apparently',
  name text not null,
  dimension text not null default 'hook',        -- hook | time | format | cta | length
  status text not null default 'active',
  created_at timestamptz not null default now()
);
create table if not exists public.growth_social_variant (
  id uuid primary key default gen_random_uuid(),
  experiment_id uuid references public.growth_social_experiment(id) on delete cascade,
  label text not null,
  spec jsonb not null default '{}'::jsonb,
  trials int not null default 0,
  reward_sum numeric not null default 0,          -- sum of engagement-rate rewards
  created_at timestamptz not null default now()
);

-- (2) Tracked-link attribution ----------------------------------------------------
create table if not exists public.growth_social_link (
  id uuid primary key default gen_random_uuid(),
  app text not null default 'apparently',
  post_id uuid,
  platform text,
  slug text unique not null,
  destination text not null,
  utm jsonb not null default '{}'::jsonb,
  clicks int not null default 0,
  conversions int not null default 0,
  revenue numeric not null default 0,
  created_at timestamptz not null default now()
);

-- (4) Social listening + reactive engagement --------------------------------------
create table if not exists public.growth_social_signal (
  id uuid primary key default gen_random_uuid(),
  app text not null default 'apparently',
  platform text not null,
  kind text not null default 'keyword',           -- mention | keyword | competitor | lead
  source_ref text, author text, text text,
  score numeric not null default 0.5,
  status text not null default 'new',             -- new | acted | ignored
  created_at timestamptz not null default now()
);
create table if not exists public.growth_listen_rule (
  id uuid primary key default gen_random_uuid(),
  app text not null default 'apparently',
  platform text not null,
  query text not null,
  action text not null default 'comment',         -- comment | like | connect | follow | dm
  account_id uuid references public.growth_channel_account(id) on delete set null,
  autonomy text not null default 'approval',
  active boolean not null default true,
  created_at timestamptz not null default now()
);

-- (5) Account warmup + team amplification -----------------------------------------
create table if not exists public.growth_account_warmup (
  account_id uuid primary key references public.growth_channel_account(id) on delete cascade,
  started_at timestamptz not null default now(),
  day int not null default 1,
  cap_multiplier numeric not null default 0.25,    -- ramps 0.25 -> 1.0 over ~14 days
  max_ramp_days int not null default 14
);

-- (6) Per-account voice profiles --------------------------------------------------
create table if not exists public.growth_voice_profile (
  account_id uuid primary key references public.growth_channel_account(id) on delete cascade,
  app text not null default 'apparently',
  tone text,
  examples jsonb not null default '[]'::jsonb,      -- best past posts to imitate
  dos jsonb not null default '[]'::jsonb,
  donts jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now()
);

-- (7) Account health / safety -----------------------------------------------------
create table if not exists public.growth_account_health (
  account_id uuid primary key references public.growth_channel_account(id) on delete cascade,
  status text not null default 'healthy',           -- healthy | watch | paused
  signals jsonb not null default '[]'::jsonb,
  action_ok int not null default 0,
  action_fail int not null default 0,
  last_checked timestamptz not null default now()
);

-- (8) Scheme marketplace outcomes -------------------------------------------------
alter table public.growth_scheme_run add column if not exists outcome_score numeric not null default 0;
alter table public.growth_scheme_run add column if not exists outcome_stats jsonb not null default '{}'::jsonb;
alter table public.growth_scheme add column if not exists outcome_stats jsonb not null default '{}'::jsonb;
alter table public.growth_scheme add column if not exists uses int not null default 0;

do $$
declare t text;
begin
  foreach t in array array['growth_social_experiment','growth_social_variant','growth_social_link',
    'growth_social_signal','growth_listen_rule','growth_account_warmup','growth_voice_profile','growth_account_health'] loop
    execute format('alter table public.%I enable row level security;', t);
  end loop;
end $$;;

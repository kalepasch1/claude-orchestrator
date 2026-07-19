-- Omnichannel social marketing extension to Growth OS.
-- Adds: channel catalog + connected accounts + credential pointers, social posts,
-- engagement actions, content calendar cadence, per-platform rate policy, and a
-- recommended-scheme catalog + runs. Idempotent; RLS default-deny (service key bypasses).

-- 1) Channel catalog (reference: platforms + capabilities) --------------------
create table if not exists public.growth_channel_catalog (
  platform text primary key,
  display_name text not null,
  family text not null default 'social',            -- social | longform | video | community
  credential_method text not null default 'oauth',  -- oauth | api_key | cookie | manual
  official_api boolean not null default true,
  capabilities jsonb not null default '{}'::jsonb,   -- {post,article,newsletter,thread,short,comment,like,connect,follow,dm,endorse}
  notes text,
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

-- 2) Connected accounts (personal or company credentials) ---------------------
create table if not exists public.growth_channel_account (
  id uuid primary key default gen_random_uuid(),
  app text not null default 'apparently',
  platform text not null references public.growth_channel_catalog(platform),
  owner text not null default 'personal',            -- personal | company
  handle text,                                       -- @handle / profile / page id
  display_name text,
  workspace_id text,
  actor_hash text,
  brand_mode text not null default 'personal',        -- personal | firm | none
  credential_method text not null default 'oauth',
  credential_ref text,                                -- pointer into vault; NEVER a raw secret
  scopes text[] not null default '{}',
  autonomy text not null default 'approval',           -- off | approval | auto
  daily_action_cap int,                                -- optional per-account override
  status text not null default 'pending',              -- pending | connected | disabled | error
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (app, platform, owner, handle)
);
create index if not exists idx_gca_app on public.growth_channel_account(app);
create index if not exists idx_gca_platform on public.growth_channel_account(platform);

-- 3) Credential pointers (vault refs only — no raw secrets) -------------------
create table if not exists public.growth_channel_credential (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.growth_channel_account(id) on delete cascade,
  method text not null default 'oauth',
  secret_ref text,                                    -- external vault / secret-manager key
  oauth_account_ref text,                             -- reuse existing OAuth token store
  expires_at timestamptz,
  status text not null default 'pending',
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_gcc_account on public.growth_channel_credential(account_id);

-- 4) Social posts (content units scheduled/published to a channel) ------------
create table if not exists public.growth_social_post (
  id uuid primary key default gen_random_uuid(),
  app text not null default 'apparently',
  account_id uuid references public.growth_channel_account(id) on delete set null,
  platform text not null,
  campaign_id uuid,
  scheme_run_id uuid,
  content_id uuid,                                    -- link to growth_content long-form source
  kind text not null default 'post',                  -- post | article | newsletter | thread | short | reel | comment
  title text,
  body text,
  media jsonb not null default '[]'::jsonb,
  hashtags text[] not null default '{}',
  autonomy text not null default 'approval',           -- off | approval | auto
  scheduled_at timestamptz,
  status text not null default 'draft',                -- draft | queued | scheduled | posting | posted | failed | skipped
  external_url text,
  metrics jsonb not null default '{}'::jsonb,          -- impressions/likes/comments/reshares/clicks
  approval_id uuid,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_gsp_app_status on public.growth_social_post(app, status);
create index if not exists idx_gsp_due on public.growth_social_post(scheduled_at) where status in ('scheduled','queued');

-- 5) Engagement actions (connect/like/comment/follow/dm/endorse) --------------
create table if not exists public.growth_social_action (
  id uuid primary key default gen_random_uuid(),
  app text not null default 'apparently',
  account_id uuid references public.growth_channel_account(id) on delete set null,
  platform text not null,
  action text not null,                                -- connect | like | comment | follow | dm | endorse | share
  target_ref text,                                     -- profile/post/company URN or url
  target_label text,
  payload jsonb not null default '{}'::jsonb,          -- e.g. comment/dm body
  scheme_run_id uuid,
  autonomy text not null default 'approval',
  scheduled_at timestamptz,
  rate_bucket date not null default (now() at time zone 'utc')::date,
  status text not null default 'proposed',             -- proposed | queued | scheduled | done | failed | skipped | rate_limited
  external_url text,
  approval_id uuid,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_gsa_app_status on public.growth_social_action(app, status);
create index if not exists idx_gsa_rate on public.growth_social_action(account_id, action, rate_bucket);

-- 6) Content calendar (recurring cadence per account/platform) ----------------
create table if not exists public.growth_content_calendar (
  id uuid primary key default gen_random_uuid(),
  app text not null default 'apparently',
  account_id uuid references public.growth_channel_account(id) on delete cascade,
  platform text not null,
  kind text not null default 'post',
  cadence text not null default 'weekly',              -- daily | weekly | biweekly | monthly
  per_period int not null default 1,
  topic_hint text,
  scheme_run_id uuid,
  next_due timestamptz not null default now(),
  active boolean not null default true,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_gcal_due on public.growth_content_calendar(next_due) where active;

-- 7) Rate policy (per platform+action daily caps — ban-avoidance rails) -------
create table if not exists public.growth_rate_policy (
  platform text not null,
  action text not null,                                -- post | connect | like | comment | follow | dm | endorse
  daily_cap int not null default 20,
  min_gap_seconds int not null default 90,
  note text,
  primary key (platform, action)
);

-- 8) Scheme catalog (pre-created / swarm-recommended marketing schemes) -------
create table if not exists public.growth_scheme (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name text not null,
  objective text not null default 'authority',         -- authority | acquisition | launch | network | nurture
  owner_default text not null default 'personal',
  platforms text[] not null default '{}',
  spec jsonb not null default '{}'::jsonb,              -- {cadence:[...], actions:[...], templates:{...}}
  recommended_for jsonb not null default '{}'::jsonb,   -- targeting hints
  source text not null default 'catalog',               -- catalog | swarm | play
  score numeric not null default 0.5,
  status text not null default 'active',
  created_at timestamptz not null default now()
);

-- 9) Scheme runs (an applied scheme instance) --------------------------------
create table if not exists public.growth_scheme_run (
  id uuid primary key default gen_random_uuid(),
  scheme_id uuid references public.growth_scheme(id),
  app text not null default 'apparently',
  account_ids uuid[] not null default '{}',
  mode text not null default 'approval',                -- off | approval | auto
  status text not null default 'active',
  stats jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- RLS default-deny on all new tables (service-role key bypasses) --------------
do $$
declare t text;
begin
  foreach t in array array[
    'growth_channel_catalog','growth_channel_account','growth_channel_credential',
    'growth_social_post','growth_social_action','growth_content_calendar',
    'growth_rate_policy','growth_scheme','growth_scheme_run'
  ] loop
    execute format('alter table public.%I enable row level security;', t);
  end loop;
end $$;;

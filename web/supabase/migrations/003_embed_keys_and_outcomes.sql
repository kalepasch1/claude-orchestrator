-- 003_embed_keys_and_outcomes.sql
--
-- Storage behind the embed SDK: tenant-scoped API keys, and the outcomes hosts
-- submit through them.
--
-- Two things are deliberate and worth not "fixing" later:
--
--   1. embed_keys stores a sha256 HASH, never the key. A read of this table
--      must not be equivalent to impersonating every host. The raw key is shown
--      once at creation time and never again.
--   2. allowed_origins is NOT NULL with no default. An empty array authorises
--      nothing (see authorizeEmbed), so a key created without thinking about
--      origins is inert rather than universal.
--
-- Idempotent, per repo convention.

create table if not exists embed_keys (
  key_id          text primary key,
  tenant_id       text not null,
  -- sha256 hex of the raw key.
  key_hash        text not null unique,
  -- Exact origins this key may be presented from. Empty = unusable.
  allowed_origins text[] not null default '{}',
  -- Surfaces this key may mount. Empty = unusable, NOT all.
  surfaces        text[] not null default '{}',
  label           text,
  revoked         boolean not null default false,
  created_at      timestamptz not null default now(),
  last_used_at    timestamptz
);
create index if not exists idx_embed_keys_tenant on embed_keys (tenant_id) where not revoked;

-- Outcomes submitted from a host app. `state` starts queued; the fleet picks
-- them up exactly as it does any other intake.
create table if not exists orch_embed_outcomes (
  id          bigserial primary key,
  tenant_id   text not null,
  host_app    text not null,
  entity_id   text,
  department  text,
  outcome     text not null,
  state       text not null default 'queued',
  task_id     text,
  created_at  timestamptz not null default now()
);
create index if not exists idx_embed_outcomes_tenant_state
  on orch_embed_outcomes (tenant_id, state, created_at desc);

-- Isolation: both tables are tenant-scoped and neither has a permissive policy.
-- The API reads them with the service role after authenticating the key, which
-- is the only path that should ever see a key hash.
alter table embed_keys           enable row level security;
alter table orch_embed_outcomes  enable row level security;

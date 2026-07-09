-- Config policy rule engine: named policy sets and their rules.
-- Encodes the safe-key logic from fleet_control._safe_key() in the DB so any
-- writer (CLI, edge function, direct SQL) is subject to enforcement at the table level.

create table if not exists config_policies (
  id          uuid primary key default gen_random_uuid(),
  name        text unique not null,
  description text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

-- rule_type:
--   deny_contains  — reject if upper(key) contains upper(pattern) (credential markers)
--   allow_prefix   — allow if upper(key) starts with upper(pattern)
--   allow_exact    — allow if upper(key) = upper(pattern) (one-off overrides)
-- Deny rules run before allow rules; lowest priority int wins ties.
create table if not exists config_rules (
  id          uuid primary key default gen_random_uuid(),
  policy_id   uuid not null references config_policies(id) on delete cascade,
  rule_type   text not null check (rule_type in ('deny_contains', 'allow_prefix', 'allow_exact')),
  pattern     text not null,
  priority    int  not null default 100,
  note        text,
  created_at  timestamptz not null default now(),
  unique (policy_id, rule_type, pattern)
);

create index if not exists config_rules_policy_type_idx
  on config_rules(policy_id, rule_type, priority);

select '0038_create_config_policy_tables OK' as status;

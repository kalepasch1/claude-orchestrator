-- Migration: operator_autoclear_rules
-- Purpose: stores rule-based auto-clear policies for operator approval cards.

create table if not exists operator_autoclear_rules (
    id          uuid primary key default gen_random_uuid(),
    project     text,           -- null = match all projects
    kind        text not null,  -- 'operator' | 'deploy' | 'secret' (never 'legal')
    max_usd     numeric,        -- null = no dollar cap; card must have an amount <= this
    enabled     boolean not null default true,
    created_at  timestamptz not null default now()
);

comment on table operator_autoclear_rules is
    'Rule-based auto-clear policies for operator approval cards. '
    'Legal cards and production-deploy cards are hard-blocked in code regardless of rules here. '
    'Cards needing 2+ approvals are also hard-blocked in code.';

comment on column operator_autoclear_rules.project is
    'Match only cards for this project slug; NULL matches any project.';

comment on column operator_autoclear_rules.max_usd is
    'If set, only auto-approve when the card detail contains a dollar amount <= this value.';;

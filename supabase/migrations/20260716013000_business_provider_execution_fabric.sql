-- Provider execution/finality fabric. Credentials remain encrypted in connector_accounts.
alter table connector_accounts add column if not exists organization_id uuid references orchestrator_organizations(id) on delete cascade;
alter table connector_accounts add column if not exists environment text not null default 'sandbox' check(environment in('sandbox','production'));
update connector_accounts c set organization_id=(select m.organization_id from orchestrator_org_memberships m where m.user_id=c.user_id and m.status='active' order by m.joined_at limit 1) where c.organization_id is null;
create index if not exists connector_accounts_org_provider_idx on connector_accounts(organization_id,provider,status,environment);

create table if not exists business_provider_executions (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid not null references agentic_business_sagas(id) on delete cascade, step_id uuid not null references agentic_business_saga_steps(id) on delete cascade,
 connector_account_id uuid not null references connector_accounts(id) on delete restrict, provider text not null, operation text not null,
 idempotency_key text not null, request_digest text not null, state text not null default 'started' check(state in('started','provider_pending','verified','failed','unknown')),
 external_ref text, receipt_digest text, response_meta jsonb not null default '{}', error_code text,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(), verified_at timestamptz,
 unique(connector_account_id,idempotency_key), unique(step_id)
);
create table if not exists business_provider_webhook_events (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 connector_account_id uuid not null references connector_accounts(id) on delete cascade, provider text not null, event_id text not null, event_type text not null,
 payload_digest text not null, verified boolean not null default false, processing_state text not null default 'accepted' check(processing_state in('accepted','matched','finalized','ignored','failed')),
 external_ref text, metadata jsonb not null default '{}', received_at timestamptz not null default now(), processed_at timestamptz,
 unique(connector_account_id,event_id)
);
create index if not exists provider_execution_state_idx on business_provider_executions(organization_id,state,updated_at);
create index if not exists provider_webhook_ref_idx on business_provider_webhook_events(provider,external_ref,received_at);
alter table business_provider_executions enable row level security;
alter table business_provider_webhook_events enable row level security;
comment on table business_provider_executions is 'Exactly-once provider mutation ledger. A provider acknowledgement is pending until webhook or read-after-write finality is verified.';
comment on table business_provider_webhook_events is 'Signature-verified, deduplicated provider events; raw sensitive payloads are never retained.';

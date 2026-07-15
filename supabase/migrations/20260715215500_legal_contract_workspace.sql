-- Effective-date legal policy compiler and proof-carrying contract lifecycle.
create table if not exists legal_policy_sources (
 id uuid primary key default gen_random_uuid(), jurisdiction text not null, domain text not null,
 title text not null, authority_url text, effective_from date not null, effective_to date,
 status text not null default 'draft' check(status in('draft','verified','superseded','withdrawn')),
 rules jsonb not null default '{}', source_digest text not null, verified_by uuid references auth.users(id),
 verified_at timestamptz, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(jurisdiction,domain,title,effective_from)
);
create table if not exists legal_policy_snapshots (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 jurisdiction text not null, domains text[] not null, as_of date not null, compiled_rules jsonb not null default '[]',
 evidence jsonb not null default '[]', professional_review_required boolean not null default true,
 review_reasons jsonb not null default '[]', coverage jsonb not null default '{}', snapshot_digest text not null,
 created_by uuid not null references auth.users(id), created_at timestamptz not null default now(),
 unique(organization_id,snapshot_digest)
);
create table if not exists legal_contracts (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 template_key text not null, category text not null, title text not null, jurisdiction text not null,
 counterparty_name text, counterparty_email text, lifecycle text not null default 'draft'
 check(lifecycle in('draft','internal_review','counterparty_review','negotiating','approval_required','approved','issue_ready','issued','partially_signed','signed','active','expired','terminated','cancelled')),
 risk_level text not null default 'high' check(risk_level in('low','medium','high')),
 policy_snapshot_id uuid references legal_policy_snapshots(id) on delete set null, current_version integer not null default 1,
 matter_data jsonb not null default '{}', professional_review_required boolean not null default true,
 smarter_sync_status text not null default 'pending' check(smarter_sync_status in('pending','synced','attention','disabled')),
 approval_id uuid references approvals(id) on delete set null, created_by uuid not null references auth.users(id),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists legal_contract_versions (
 id uuid primary key default gen_random_uuid(), contract_id uuid not null references legal_contracts(id) on delete cascade,
 version integer not null, source text not null check(source in('template','ai_prompt','redline','negotiation','counsel','accepted')),
 content jsonb not null default '{}', rendered_text text not null, change_summary text, content_digest text not null,
 created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), unique(contract_id,version)
);
create table if not exists legal_contract_reviews (
 id uuid primary key default gen_random_uuid(), contract_id uuid not null references legal_contracts(id) on delete cascade,
 version integer not null, reviewer_type text not null check(reviewer_type in('cade','hivemind','internal','counsel','counterparty')),
 status text not null check(status in('clear','attention','blocked','accepted','changes_requested')),
 score numeric not null default 0 check(score between 0 and 1), findings jsonb not null default '[]', evidence jsonb not null default '{}',
 reviewer_id uuid references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists legal_negotiation_events (
 id uuid primary key default gen_random_uuid(), contract_id uuid not null references legal_contracts(id) on delete cascade,
 from_version integer not null, to_version integer not null, actor text not null, event_type text not null,
 operations jsonb not null default '[]', rationale text, created_by uuid references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists legal_obligations (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 contract_id uuid not null references legal_contracts(id) on delete cascade, owner text, obligation text not null,
 due_at timestamptz, recurrence text, status text not null default 'open' check(status in('open','due','completed','waived','breached')),
 source_clause text, evidence jsonb not null default '{}', created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists legal_delivery_events (
 id uuid primary key default gen_random_uuid(), contract_id uuid not null references legal_contracts(id) on delete cascade,
 event_type text not null check(event_type in('smarter_sync','issue','signature_request','signature_received','reminder','archive')),
 status text not null check(status in('prepared','sent','confirmed','blocked','failed')),
 provider text, recipient text, external_ref text, evidence jsonb not null default '{}',
 created_by uuid references auth.users(id), created_at timestamptz not null default now()
);
create index if not exists legal_contracts_org_lifecycle_idx on legal_contracts(organization_id,lifecycle,updated_at desc);
create index if not exists legal_reviews_contract_version_idx on legal_contract_reviews(contract_id,version,created_at desc);
create index if not exists legal_obligations_org_due_idx on legal_obligations(organization_id,status,due_at);
alter table legal_policy_sources enable row level security;
alter table legal_policy_snapshots enable row level security;
alter table legal_contracts enable row level security;
alter table legal_contract_versions enable row level security;
alter table legal_contract_reviews enable row level security;
alter table legal_negotiation_events enable row level security;
alter table legal_obligations enable row level security;
alter table legal_delivery_events enable row level security;

create or replace function create_legal_contract_draft(
 p_organization_id uuid,p_created_by uuid,p_template_key text,p_category text,p_title text,p_jurisdiction text,
 p_counterparty_name text,p_counterparty_email text,p_risk_level text,p_policy_snapshot_id uuid,p_matter_data jsonb,
 p_professional_review_required boolean,p_content jsonb,p_rendered_text text,p_content_digest text
) returns legal_contracts language plpgsql security definer set search_path=public as $$
declare v_contract legal_contracts;
begin
 insert into legal_contracts(organization_id,template_key,category,title,jurisdiction,counterparty_name,counterparty_email,risk_level,policy_snapshot_id,matter_data,professional_review_required,created_by)
 values(p_organization_id,p_template_key,p_category,p_title,p_jurisdiction,p_counterparty_name,p_counterparty_email,p_risk_level,p_policy_snapshot_id,p_matter_data,p_professional_review_required,p_created_by) returning * into v_contract;
 insert into legal_contract_versions(contract_id,version,source,content,rendered_text,change_summary,content_digest,created_by)
 values(v_contract.id,1,'ai_prompt',p_content,p_rendered_text,'Initial template and prompt merge',p_content_digest,p_created_by);
 return v_contract;
end $$;
revoke all on function create_legal_contract_draft(uuid,uuid,text,text,text,text,text,text,text,uuid,jsonb,boolean,jsonb,text,text) from public;
grant execute on function create_legal_contract_draft(uuid,uuid,text,text,text,text,text,text,text,uuid,jsonb,boolean,jsonb,text,text) to service_role;

comment on table legal_policy_snapshots is 'Immutable effective-date workflow snapshots; not legal opinions and not a substitute for qualified jurisdiction-specific review.';
comment on table legal_contract_reviews is 'CADE/Hivemind findings are decision support. Counsel status must be recorded separately when professional review is required.';

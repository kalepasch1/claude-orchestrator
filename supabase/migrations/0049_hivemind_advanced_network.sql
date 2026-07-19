-- Advanced Hivemind: privacy budgets, causal settlement, compatibility, immunity, escrow, and anti-fraud.
alter table public.hivemind_sharing_policies add column if not exists privacy_budget_points int not null default 100 check(privacy_budget_points between 10 and 1000);
alter table public.hivemind_capability_adoptions add column if not exists baseline_value_cents bigint not null default 0;
alter table public.hivemind_capability_adoptions add column if not exists counterfactual jsonb not null default '{}';
alter table public.hivemind_capability_adoptions add column if not exists compatibility_plan_id uuid;

create table if not exists public.hivemind_disclosure_receipts (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
 subject_type text not null, subject_id uuid, requested_fields text[] not null default '{}', approved_fields text[] not null default '{}', rejected_fields text[] not null default '{}',
 inference_risk int not null check(inference_risk between 0 and 100), budget_cost int not null check(budget_cost>=0), budget_remaining int not null check(budget_remaining>=0), decision text not null check(decision in('allow','review','redact')),
 audience text not null default 'member_network', policy jsonb not null default '{}', receipt_digest text not null unique, created_by uuid references auth.users(id), created_at timestamptz not null default now());

create table if not exists public.hivemind_compatibility_plans (
 id uuid primary key default gen_random_uuid(), contribution_id uuid not null references public.hivemind_capability_contributions(id) on delete cascade,
 organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade, project_id uuid references public.projects(id) on delete set null,
 environment_profile jsonb not null default '{}', adapter_plan jsonb not null default '{}', risk_register jsonb not null default '{}', required_tests jsonb not null default '{}',
 plan_digest text not null unique, status text not null default 'draft' check(status in('draft','approved','canary','verified','rejected')), created_by uuid references auth.users(id), created_at timestamptz not null default now());

create table if not exists public.hivemind_immune_signals (
 id uuid primary key default gen_random_uuid(), contribution_id uuid references public.hivemind_capability_contributions(id) on delete cascade,
 source_organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade, signal_class text not null, severity text not null check(severity in('low','medium','high','critical')),
 sanitized_signature jsonb not null, affected_versions text[] not null default '{}', recommended_response jsonb not null default '{}', raw_evidence_shared boolean not null default false,
 signal_digest text not null unique, status text not null default 'active' check(status in('active','contained','retracted')), created_at timestamptz not null default now());

create table if not exists public.hivemind_fraud_assessments (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
 subject_type text not null, subject_id uuid not null, signals jsonb not null default '[]', risk_score int not null check(risk_score between 0 and 100),
 verdict text not null check(verdict in('clear','review','blocked')), assessment_digest text not null unique, created_at timestamptz not null default now());

create table if not exists public.hivemind_capability_escrows (
 id uuid primary key default gen_random_uuid(), contribution_id uuid not null references public.hivemind_capability_contributions(id) on delete cascade,
 owner_organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade, encrypted_payload text not null, payload_digest text not null unique,
 release_policy jsonb not null, license_terms jsonb not null, status text not null default 'sealed' check(status in('sealed','licensed','revoked')), created_by uuid references auth.users(id), created_at timestamptz not null default now());

create table if not exists public.hivemind_causal_settlements (
 id uuid primary key default gen_random_uuid(), adoption_id uuid not null unique references public.hivemind_capability_adoptions(id) on delete cascade,
 treatment jsonb not null, counterfactual jsonb not null, incremental_value_cents bigint not null, confidence numeric not null check(confidence between 0 and 1),
 fraud_assessment_id uuid references public.hivemind_fraud_assessments(id), rebate_cents bigint not null default 0, decision text not null check(decision in('insufficient_evidence','review','settle','blocked')),
 proof_digest text not null unique, created_at timestamptz not null default now());

create table if not exists public.hivemind_synthetic_cohorts (
 id uuid primary key default gen_random_uuid(), cohort_key text not null unique, public_profile jsonb not null, synthetic_benchmarks jsonb not null,
 source_count int not null default 0, privacy_model jsonb not null, generated_at timestamptz not null default now());

create table if not exists public.hivemind_opportunities (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
 opportunity_type text not null, title text not null, explanation text not null, predicted_value_cents bigint not null default 0, confidence numeric not null check(confidence between 0 and 1),
 source_refs jsonb not null default '{}', consent_requirements jsonb not null default '{}', next_action jsonb not null default '{}', status text not null default 'open' check(status in('open','accepted','dismissed','completed')),
 created_at timestamptz not null default now());

create index if not exists idx_hive_disclosures_org_time on public.hivemind_disclosure_receipts(organization_id,created_at desc);
create index if not exists idx_hive_immune_active on public.hivemind_immune_signals(contribution_id,status,severity);
create index if not exists idx_hive_opportunities_org on public.hivemind_opportunities(organization_id,status,predicted_value_cents desc);
alter table public.hivemind_disclosure_receipts enable row level security; alter table public.hivemind_compatibility_plans enable row level security;
alter table public.hivemind_immune_signals enable row level security; alter table public.hivemind_fraud_assessments enable row level security;
alter table public.hivemind_capability_escrows enable row level security; alter table public.hivemind_causal_settlements enable row level security;
alter table public.hivemind_synthetic_cohorts enable row level security; alter table public.hivemind_opportunities enable row level security;

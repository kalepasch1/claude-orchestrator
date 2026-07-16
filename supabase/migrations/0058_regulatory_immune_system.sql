-- Regulatory immune system: verified law-to-runtime controls, agentic swarm
-- certification, cross-border clearing, proof portability, bounded regulator
-- streams, enforcement rehearsal, and authority-decay prioritization.

create table if not exists public.regulatory_compiled_controls (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  source_ref text not null, source_digest text not null, provisions jsonb not null default '[]', runtime_controls jsonb not null default '[]',
  traceability jsonb not null default '[]', test_vectors jsonb not null default '[]', unresolved_interpretations jsonb not null default '[]',
  effective_from timestamptz, expires_at timestamptz, compiler_digest text not null unique,
  status text not null default 'shadow' check (status in ('shadow','review','approved','active','superseded','revoked')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_swarm_certifications (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  subject_ref text not null, sponsor_relationship_id uuid references public.regulatory_relationships(id) on delete set null,
  shadow_history jsonb not null default '{}', agent_assessments jsonb not null default '[]', reconciled_findings jsonb not null default '[]',
  contradictions jsonb not null default '[]', material_risks jsonb not null default '[]', evidence_gaps jsonb not null default '[]',
  confidence numeric not null default 0, human_escalation_required boolean not null default true, escalation_reasons jsonb not null default '[]',
  recommendation text not null default 'hold', certification_digest text not null unique,
  status text not null default 'swarm_reviewed' check (status in ('swarm_reviewed','human_review','eligible','declined','expired')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_immune_events (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  signal_ref text not null, affected_boundary jsonb not null default '{}', diagnosis jsonb not null default '{}', isolation_plan jsonb not null default '[]',
  lawful_substitute jsonb not null default '{}', remediation_evidence jsonb not null default '[]', reentry_plan jsonb not null default '[]',
  autonomous_actions jsonb not null default '[]', approval_required_actions jsonb not null default '[]', severity text not null,
  event_digest text not null unique, status text not null default 'contained' check (status in ('observed','contained','remediating','reentry_review','resolved')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_clearing_matches (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  activity text not null, jurisdictions jsonb not null default '[]', requirements jsonb not null default '[]', candidates jsonb not null default '[]',
  recommended_bundle jsonb not null default '{}', conflicts jsonb not null default '[]', economics jsonb not null default '{}', execution_plan jsonb not null default '[]',
  consent_requirements jsonb not null default '[]', match_digest text not null unique,
  status text not null default 'modeled' check (status in ('modeled','permission_required','introduced','negotiating','active','dismissed')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_proof_modules (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  module_key text not null, control_family text not null, jurisdiction_scope jsonb not null default '[]', proof_manifest jsonb not null default '{}',
  portability_constraints jsonb not null default '[]', privacy_tier text not null default 'aggregate', verified_uses int not null default 0,
  recipient_savings_cents bigint not null default 0, contributor_rebate_cents bigint not null default 0, module_digest text not null unique,
  status text not null default 'private' check (status in ('private','permissioned','listed','suspended','retired')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_evidence_streams (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  grant_id uuid references public.regulatory_access_grants(id) on delete cascade, recipient_ref text not null, purpose text not null,
  field_allowlist jsonb not null default '[]', source_refs jsonb not null default '[]', delivery_manifest jsonb not null default '[]',
  denied_fields jsonb not null default '[]',
  cadence text not null default 'on_change', expires_at timestamptz not null, last_delivered_at timestamptz, stream_digest text not null unique,
  status text not null default 'shadow' check (status in ('shadow','active','paused','expired','revoked')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_enforcement_rehearsals (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  target_ref text not null, alleged_findings jsonb not null default '[]', enforcement_path jsonb not null default '[]', remediation_orders jsonb not null default '[]',
  customer_restitution_cents bigint not null default 0, interruption_days numeric not null default 0, defense_options jsonb not null default '[]',
  evidence_gaps jsonb not null default '[]', containment_actions jsonb not null default '[]', rehearsal_digest text not null unique,
  status text not null default 'modeled' check (status in ('modeled','accepted','remediating','superseded')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_authority_decay_budget (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  asset_type text not null, asset_ref text not null, current_value_cents bigint not null default 0, decay_rate_daily numeric not null default 0,
  days_to_material_loss int not null default 0, triggers jsonb not null default '[]', preservation_options jsonb not null default '[]',
  recommended_action jsonb not null default '{}', priority_score int not null default 0, budget_digest text not null unique,
  status text not null default 'current' check (status in ('current','actioned','stabilized','expired','retired')), calculated_at timestamptz not null default now(), created_at timestamptz not null default now()
);

create index if not exists idx_reg_compiled_org on public.regulatory_compiled_controls(organization_id,status,created_at desc);
create index if not exists idx_reg_swarm_org on public.regulatory_swarm_certifications(organization_id,status,created_at desc);
create index if not exists idx_reg_immune_org on public.regulatory_immune_events(organization_id,status,created_at desc);
create index if not exists idx_reg_clearing_org on public.regulatory_clearing_matches(organization_id,status,created_at desc);
create index if not exists idx_reg_proof_module_org on public.regulatory_proof_modules(organization_id,status,created_at desc);
create index if not exists idx_reg_stream_org on public.regulatory_evidence_streams(organization_id,status,expires_at);
create index if not exists idx_reg_enforcement_org on public.regulatory_enforcement_rehearsals(organization_id,status,created_at desc);
create index if not exists idx_reg_decay_org on public.regulatory_authority_decay_budget(organization_id,status,priority_score desc);

alter table public.regulatory_compiled_controls enable row level security;
alter table public.regulatory_swarm_certifications enable row level security;
alter table public.regulatory_immune_events enable row level security;
alter table public.regulatory_clearing_matches enable row level security;
alter table public.regulatory_proof_modules enable row level security;
alter table public.regulatory_evidence_streams enable row level security;
alter table public.regulatory_enforcement_rehearsals enable row level security;
alter table public.regulatory_authority_decay_budget enable row level security;

comment on table public.regulatory_swarm_certifications is 'Independent agentic first-pass review; material risk, contradictions, missing authority, and evidence gaps fail closed to human review.';
comment on table public.regulatory_compiled_controls is 'Machine-testable shadow controls traceable to supplied authority sources; unresolved legal interpretation cannot autonomously activate.';
comment on table public.regulatory_evidence_streams is 'Explicitly granted, purpose-bound, field-limited, expiring evidence delivery. No grant means no delivery.';

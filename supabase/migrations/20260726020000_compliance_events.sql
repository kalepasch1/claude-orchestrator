-- Create compliance_events table for real-time regulatory monitoring
create table if not exists compliance_events (
  id uuid primary key default gen_random_uuid(),
  project_id text not null,
  dag_id text,
  task_slug text,
  risk_category text not null check (risk_category in (
    'pii_exposure','auth_change','payment_change','data_retention',
    'third_party_sdk','license_violation','accessibility','gdpr',
    'hipaa','sox','regulatory_filing','encryption','api_security',
    'data_residency','consent_flow','audit_trail'
  )),
  severity text not null check (severity in ('info','low','medium','high','critical')),
  summary text not null,
  file_path text,
  diff_excerpt text,
  auto_resolved boolean not null default false,
  resolution text,
  escalated boolean not null default false,
  escalated_to text,
  acknowledged boolean not null default false,
  acknowledged_by text,
  created_at timestamptz not null default now()
);

create index if not exists idx_compliance_events_severity on compliance_events(severity) where severity in ('high','critical');
create index if not exists idx_compliance_events_project on compliance_events(project_id, created_at desc);
create index if not exists idx_compliance_events_unack on compliance_events(acknowledged) where acknowledged = false;

alter table compliance_events enable row level security;
create policy if not exists "Service role full access" on compliance_events
  for all using (auth.role() = 'service_role');

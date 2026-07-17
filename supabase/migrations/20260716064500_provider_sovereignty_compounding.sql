-- Compounding provider sovereignty: threshold proofs, live auctions, semantic
-- mutation identity, transparency, inferred state machines, treasury planning,
-- regulatory impact simulation, and saga model checking.
create table if not exists provider_threshold_aggregate_proofs (
 id uuid primary key default gen_random_uuid(), aggregate_digest text not null unique,
 signer_key_ids text[] not null, signatures jsonb not null, quorum integer not null check(quorum>=2),
 transcript_digest text not null, zk_verifier_receipt jsonb, verified boolean not null default false,
 verified_at timestamptz, created_at timestamptz not null default now()
);
create table if not exists provider_route_auctions (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid not null references agentic_business_sagas(id) on delete cascade, step_id uuid not null references agentic_business_saga_steps(id) on delete cascade,
 request_digest text not null, quotes jsonb not null, selected_connector_account_id uuid references connector_accounts(id) on delete set null,
 selection_digest text not null, quote_count integer not null, live_quote_count integer not null default 0,
 status text not null check(status in('selected','no_safe_quote','unavailable')), expires_at timestamptz, created_at timestamptz not null default now(),
 unique(step_id,request_digest)
);
create table if not exists provider_semantic_mutation_intents (
 id uuid primary key default gen_random_uuid(), semantic_key text not null unique, organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid references agentic_business_sagas(id) on delete set null, step_id uuid references agentic_business_saga_steps(id) on delete set null,
 operation text not null, obligation_digest text not null, signed_intent jsonb not null, state text not null default 'claimed' check(state in('claimed','committed','failed')),
 provider text, external_ref text, receipt_digest text, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists provider_transparency_entries (
 sequence bigint generated always as identity primary key, organization_id uuid references orchestrator_organizations(id) on delete set null,
 entry_type text not null, subject_digest text not null, payload_digest text not null, previous_entry_hash text,
 entry_hash text not null unique, signer_key_id text, signature text, created_at timestamptz not null default now()
);
create table if not exists provider_inferred_state_machines (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 adapter_id uuid not null references provider_adapter_manifests(id) on delete cascade, operation text not null,
 states jsonb not null, transitions jsonb not null, terminals text[] not null, invariants jsonb not null,
 coverage numeric not null check(coverage between 0 and 1), model_check jsonb not null, machine_digest text not null,
 status text not null check(status in('verified','insufficient_evidence','rejected')), created_at timestamptz not null default now(), unique(adapter_id,operation,machine_digest)
);
create table if not exists provider_treasury_plans (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 horizon_at timestamptz not null, currency text not null, obligations jsonb not null, rails jsonb not null, schedule jsonb not null,
 projected_idle_cash numeric not null default 0, projected_shortfall numeric not null default 0, expected_cost numeric not null default 0,
 approval_actions jsonb not null default '[]', plan_digest text not null, state text not null default 'proposed' check(state in('proposed','approved','superseded','executed')),
 created_by uuid references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,plan_digest)
);
create table if not exists provider_regulatory_impact_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 snapshot_id uuid not null references provider_authority_snapshots(id) on delete cascade, impacted_resources jsonb not null,
 impact_count integer not null, risk_summary jsonb not null, simulation_digest text not null,
 professional_review_required boolean not null default true, created_at timestamptz not null default now(), unique(snapshot_id,simulation_digest)
);
create table if not exists provider_saga_model_checks (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid not null references agentic_business_sagas(id) on delete cascade, model_version text not null,
 explored_states integer not null, invariants jsonb not null, counterexamples jsonb not null, model_digest text not null,
 status text not null check(status in('passed','failed')), created_at timestamptz not null default now(), unique(saga_id,model_digest)
);

create or replace function append_provider_transparency_entry(p_organization_id uuid,p_entry_type text,p_subject_digest text,p_payload_digest text,p_signer_key_id text,p_signature text)
returns provider_transparency_entries language plpgsql security definer set search_path=public as $$
declare prior text; r provider_transparency_entries;
begin
 perform pg_advisory_xact_lock(hashtextextended('provider-transparency-log',47));
 select entry_hash into prior from provider_transparency_entries order by sequence desc limit 1;
 insert into provider_transparency_entries(organization_id,entry_type,subject_digest,payload_digest,previous_entry_hash,entry_hash,signer_key_id,signature)
 values(p_organization_id,p_entry_type,p_subject_digest,p_payload_digest,prior,encode(digest(coalesce(prior,'genesis')||':'||p_entry_type||':'||p_subject_digest||':'||p_payload_digest,'sha256'),'hex'),p_signer_key_id,p_signature)
 returning * into r; return r;
end $$;
revoke all on function append_provider_transparency_entry(uuid,text,text,text,text,text) from public;
grant execute on function append_provider_transparency_entry(uuid,text,text,text,text,text) to service_role;

create or replace function log_provider_tee_transparency() returns trigger language plpgsql security definer set search_path=public as $$
declare prior text; subject text; payload text;
begin
 perform pg_advisory_xact_lock(hashtextextended('provider-transparency-log',47));
 select entry_hash into prior from provider_transparency_entries order by sequence desc limit 1;
 subject:=new.attestation_digest; payload:=encode(digest(new.measurement||':'||new.platform||':'||new.lease_id,'sha256'),'hex');
 insert into provider_transparency_entries(organization_id,entry_type,subject_digest,payload_digest,previous_entry_hash,entry_hash,signer_key_id,signature)
 values(new.organization_id,'tee_measurement_verified',subject,payload,prior,encode(digest(coalesce(prior,'genesis')||':tee_measurement_verified:'||subject||':'||payload,'sha256'),'hex'),'database-trigger',null);
 return new;
end $$;
drop trigger if exists provider_tee_transparency_trigger on provider_tee_attestations;
create trigger provider_tee_transparency_trigger after insert on provider_tee_attestations for each row when(new.verified=true) execute function log_provider_tee_transparency();

create index if not exists provider_route_auction_step_idx on provider_route_auctions(step_id,created_at desc);
create index if not exists provider_transparency_subject_idx on provider_transparency_entries(subject_digest,sequence desc);
create index if not exists provider_treasury_plan_latest_idx on provider_treasury_plans(organization_id,currency,created_at desc);
do $$ declare t text; begin foreach t in array array['provider_threshold_aggregate_proofs','provider_route_auctions','provider_semantic_mutation_intents','provider_transparency_entries','provider_inferred_state_machines','provider_treasury_plans','provider_regulatory_impact_runs','provider_saga_model_checks'] loop execute format('alter table %I enable row level security',t); end loop; end $$;

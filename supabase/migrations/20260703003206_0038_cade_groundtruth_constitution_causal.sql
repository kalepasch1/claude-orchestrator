-- GROUND-TRUTH: realized outcome per determination (the label that grounds all calibration/learning)
create table if not exists determination_outcomes (
  id uuid primary key default gen_random_uuid(),
  determination_id uuid, subject_id uuid, metric text,
  value_before numeric, value_after numeric, delta numeric,
  labeled_outcome numeric,          -- +1 good / -1 bad / 0 neutral
  causal_lift numeric, is_holdout boolean default false,
  source text, created_at timestamptz default now()
);
create index if not exists idx_detout_subj on determination_outcomes(subject_id);

-- CONSTITUTION-AS-CODE: hard, machine-checked predicates that gate determinations
create table if not exists constitution_rules (
  id uuid primary key default gen_random_uuid(),
  name text, predicate text, severity text default 'block', active boolean default true, params jsonb
);
create table if not exists constitution_checks (
  id uuid primary key default gen_random_uuid(),
  determination_id uuid, rule text, passed boolean, detail text, created_at timestamptz default now()
);
insert into constitution_rules (name, predicate, severity) values
  ('no_autonomous_money_movement','no_money_movement','block'),
  ('legal_veto_is_absolute','legal_veto_blocks','block'),
  ('privacy_seated_on_user_data','privacy_required','warn'),
  ('irreversible_needs_human','reversibility_gate','block')
on conflict do nothing;

-- INSTANT actions: a trigger fulfills DB-only reviewer actions (approve/override) synchronously on insert
create or replace function handle_determination_action() returns trigger as $$
declare rec text;
begin
  if NEW.action in ('approve','override') then
    select recommendation into rec from determinations where id = NEW.determination_id;
    insert into owner_overrides (subject_type, subject_id, committee_rec, owner_decision, direction)
      values ('determination', NEW.determination_id, rec, NEW.action,
        case when NEW.action='approve' and rec ~ '^(HOLD|ESCALATE)' then 'owner_more_aggressive'
             when NEW.action='override' then 'owner_more_cautious' else 'aligned' end);
    NEW.status := 'done';
    NEW.result := jsonb_build_object('status', NEW.action, 'instant', true, 'recorded', 'owner_override');
    NEW.done_at := now();
  end if;
  return NEW;
end; $$ language plpgsql;

drop trigger if exists trg_determination_action on determination_actions;
create trigger trg_determination_action before insert on determination_actions
  for each row execute function handle_determination_action();;

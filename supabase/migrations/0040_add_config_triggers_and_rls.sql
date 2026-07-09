-- Trigger on fleet_config: reject unsafe keys at write time, regardless of caller.
-- RLS on config_policies/config_rules: authenticated users read-only; only service role writes.
-- Seed: fleet_safety policy that mirrors fleet_control._safe_key() exactly.

create or replace function enforce_config_key_policy() returns trigger language plpgsql as $$
begin
  if not validate_config_key(new.key) then
    raise exception
      'fleet_config: key ''%'' rejected by safety policy (credential marker or unknown prefix)', new.key;
  end if;
  return new;
end $$;

drop trigger if exists fleet_config_policy_check on fleet_config;
create trigger fleet_config_policy_check
  before insert or update of key on fleet_config
  for each row execute function enforce_config_key_policy();

-- RLS: policy/rule metadata is readable by authenticated clients but only writable via service role.
alter table config_policies enable row level security;
alter table config_rules enable row level security;

do $$
begin
  execute 'drop policy if exists config_policies_authenticated_read on config_policies';
  execute 'create policy config_policies_authenticated_read on config_policies
             for select to authenticated using (true)';
  execute 'drop policy if exists config_rules_authenticated_read on config_rules';
  execute 'create policy config_rules_authenticated_read on config_rules
             for select to authenticated using (true)';
end $$;

-- Seed the fleet_safety policy: deny credential markers, allow known safe prefixes.
-- This is the canonical DB representation of fleet_control._safe_key() / fleetctl._set_config().
do $$
declare
  pid uuid;
begin
  insert into config_policies(name, description)
  values (
    'fleet_safety',
    'Deny credential markers; allow safe orchestrator prefixes. Mirrors fleet_control._safe_key().'
  )
  on conflict (name) do update set description = excluded.description
  returning id into pid;

  -- deny rules (credential markers — substring match)
  insert into config_rules(policy_id, rule_type, pattern, priority, note) values
    (pid, 'deny_contains', 'KEY',        10, 'API keys, private keys, etc.'),
    (pid, 'deny_contains', 'SECRET',     10, 'Shared secrets'),
    (pid, 'deny_contains', 'TOKEN',      10, 'Auth/API tokens'),
    (pid, 'deny_contains', 'PASSWORD',   10, 'Passwords'),
    (pid, 'deny_contains', 'PWD',        10, 'Password abbreviation'),
    (pid, 'deny_contains', 'CREDENTIAL', 10, 'Credentials')
  on conflict (policy_id, rule_type, pattern) do nothing;

  -- allow rules (safe prefixes — same list as _SAFE_PREFIXES in fleet_control.py)
  insert into config_rules(policy_id, rule_type, pattern, priority, note) values
    (pid, 'allow_prefix', 'ORCH_',            100, 'Orchestrator settings'),
    (pid, 'allow_prefix', 'MAX_PARALLEL',     100, 'Parallelism limits'),
    (pid, 'allow_prefix', 'PER_TASK_GB',      100, 'Per-task memory cap'),
    (pid, 'allow_prefix', 'RAM_FLOOR_GB',     100, 'RAM floor (exact prefix before _ variants)'),
    (pid, 'allow_prefix', 'RAM_',             100, 'All RAM-related settings'),
    (pid, 'allow_prefix', 'RELEASE_',         100, 'Release control flags'),
    (pid, 'allow_prefix', 'QUEUE_',           100, 'Queue settings'),
    (pid, 'allow_prefix', 'CONT_',            100, 'Container settings'),
    (pid, 'allow_prefix', 'JANITOR_',         100, 'Cleanup/janitor settings'),
    (pid, 'allow_prefix', 'REMEDIATION_',     100, 'Remediation settings'),
    (pid, 'allow_prefix', 'DEFAULT_TEST_CMD', 100, 'Default test command'),
    (pid, 'allow_prefix', 'TASK_TIMEOUT',     100, 'Task timeout settings'),
    (pid, 'allow_prefix', 'ENABLE_',          100, 'Feature enable flags'),
    (pid, 'allow_prefix', 'SESSION_',         100, 'Session settings'),
    (pid, 'allow_prefix', 'ACCOUNT_COOLDOWN', 100, 'Account cooldown'),
    (pid, 'allow_prefix', 'MERGE_',           100, 'Merge control flags'),
    (pid, 'allow_prefix', 'DEPLOY_',          100, 'Deploy settings'),
    (pid, 'allow_prefix', 'INTEGRATE_',       100, 'Integration settings'),
    (pid, 'allow_prefix', 'COST_',            100, 'Cost management settings')
  on conflict (policy_id, rule_type, pattern) do nothing;
end $$;

select '0040_add_config_triggers_and_rls OK – policy: fleet_safety, rules: '
       || (select count(*) from config_rules) || ' total'
  as status;

-- Acceptance tests for the config policy rule engine (migrations 0038-0040).
-- Run against a live Supabase instance after applying the migrations.
-- All test data is written inside a transaction and rolled back at the end.

begin;

create or replace function _assert(cond boolean, msg text) returns void language plpgsql as $$
begin
  if not cond then raise exception 'ASSERTION FAILED: %', msg; end if;
end $$;

-- 1. fleet_safety policy exists and is active
select _assert(
  (select is_active from config_policies where name = 'fleet_safety'),
  '1: fleet_safety policy should exist and be active'
);

select _assert(
  (select count(*) from config_rules where rule_type = 'deny_contains') >= 6,
  '1: at least 6 deny_contains rules should be seeded'
);

select _assert(
  (select count(*) from config_rules where rule_type = 'allow_prefix') >= 19,
  '1: at least 19 allow_prefix rules should be seeded'
);

-- 2. validate_config_key: known-safe prefixes are allowed
select _assert(validate_config_key('ORCH_AUTO_PULL'),      '2: ORCH_ prefix allowed');
select _assert(validate_config_key('ORCH_FLEET_TICK_S'),   '2: ORCH_ prefix allowed');
select _assert(validate_config_key('MAX_PARALLEL_TASKS'),  '2: MAX_PARALLEL prefix allowed');
select _assert(validate_config_key('PER_TASK_GB'),         '2: PER_TASK_GB prefix allowed');
select _assert(validate_config_key('RAM_FLOOR_GB'),        '2: RAM_FLOOR_GB prefix allowed');
select _assert(validate_config_key('RAM_USAGE'),           '2: RAM_ prefix allowed');
select _assert(validate_config_key('RELEASE_VERSION'),     '2: RELEASE_ prefix allowed');
select _assert(validate_config_key('QUEUE_MAX_SIZE'),      '2: QUEUE_ prefix allowed');
select _assert(validate_config_key('CONT_RESTART_DELAY'),  '2: CONT_ prefix allowed');
select _assert(validate_config_key('JANITOR_INTERVAL'),    '2: JANITOR_ prefix allowed');
select _assert(validate_config_key('REMEDIATION_MAX'),     '2: REMEDIATION_ prefix allowed');
select _assert(validate_config_key('DEFAULT_TEST_CMD'),    '2: DEFAULT_TEST_CMD prefix allowed');
select _assert(validate_config_key('TASK_TIMEOUT'),        '2: TASK_TIMEOUT prefix allowed');
select _assert(validate_config_key('ENABLE_FEATURE_X'),   '2: ENABLE_ prefix allowed');
select _assert(validate_config_key('SESSION_TTL'),         '2: SESSION_ prefix allowed');
select _assert(validate_config_key('ACCOUNT_COOLDOWN'),    '2: ACCOUNT_COOLDOWN prefix allowed');
select _assert(validate_config_key('MERGE_STRATEGY'),      '2: MERGE_ prefix allowed');
select _assert(validate_config_key('DEPLOY_TIMEOUT'),      '2: DEPLOY_ prefix allowed');
select _assert(validate_config_key('INTEGRATE_MODE'),      '2: INTEGRATE_ prefix allowed');
select _assert(validate_config_key('COST_THRESHOLD'),      '2: COST_ prefix allowed');

-- 3. validate_config_key: credential markers are denied (substring match, case-insensitive)
select _assert(not validate_config_key('MY_API_KEY'),       '3: KEY marker denied');
select _assert(not validate_config_key('SOME_SECRET'),      '3: SECRET marker denied');
select _assert(not validate_config_key('AUTH_TOKEN'),       '3: TOKEN marker denied');
select _assert(not validate_config_key('DB_PASSWORD'),      '3: PASSWORD marker denied');
select _assert(not validate_config_key('DB_PWD'),           '3: PWD marker denied');
select _assert(not validate_config_key('AWS_CREDENTIAL'),   '3: CREDENTIAL marker denied');
select _assert(not validate_config_key('OPENAI_API_KEY'),   '3: KEY marker denied (compound)');

-- 4. deny beats allow — safe prefix + credential marker → still denied
select _assert(not validate_config_key('ORCH_SECRET_CONFIG'),  '4: SECRET overrides ORCH_ prefix');
select _assert(not validate_config_key('DEPLOY_TOKEN'),        '4: TOKEN overrides DEPLOY_ prefix');
select _assert(not validate_config_key('ORCH_DB_PASSWORD'),    '4: PASSWORD overrides ORCH_ prefix');
select _assert(not validate_config_key('ENABLE_API_KEY'),      '4: KEY overrides ENABLE_ prefix');

-- 5. unknown / bare keys denied by default
select _assert(not validate_config_key('UNKNOWN_VAR'),  '5: unknown prefix denied');
select _assert(not validate_config_key('DEBUG'),         '5: bare key denied');
select _assert(not validate_config_key(''),              '5: empty key denied');

-- 6. apply_config_policy: bulk validation
do $$
declare bad text[];
begin
  bad := apply_config_policy('{"ORCH_FOO":"bar","MAX_PARALLEL":"4","DEPLOY_ENV":"prod"}'::jsonb);
  perform _assert(cardinality(bad) = 0, '6: all-safe bulk returns empty rejected');

  bad := apply_config_policy('{"ORCH_FOO":"bar","MY_API_KEY":"secret"}'::jsonb);
  perform _assert('MY_API_KEY' = any(bad), '6: MY_API_KEY in rejected list');
  perform _assert(not ('ORCH_FOO' = any(bad)), '6: ORCH_FOO not in rejected list');

  bad := apply_config_policy('{}'::jsonb);
  perform _assert(cardinality(bad) = 0, '6: empty config returns empty rejected');
end $$;

-- 7. fleet_config trigger: safe key insert/upsert succeeds
insert into fleet_config(key, value, note, updated_by)
values ('ORCH_TEST_POLICY_CHECK', 'acceptance_pass', 'acceptance test row', 'test')
on conflict (key) do update set value = 'acceptance_pass', updated_at = now();

select _assert(
  (select value from fleet_config where key = 'ORCH_TEST_POLICY_CHECK') = 'acceptance_pass',
  '7: safe key insert should succeed'
);

-- 8. fleet_config trigger: unsafe key insert raises exception
do $$
declare caught boolean := false;
begin
  begin
    insert into fleet_config(key, value) values ('MY_API_SECRET_KEY', 'hunter2');
  exception when others then caught := true;
  end;
  perform _assert(caught, '8: unsafe key insert must raise exception from trigger');
end $$;

-- 9. trigger enforces deny-beats-allow at write time
do $$
declare caught boolean := false;
begin
  begin
    insert into fleet_config(key, value) values ('ORCH_API_KEY', 'should_be_blocked');
  exception when others then caught := true;
  end;
  perform _assert(caught, '9: ORCH_ + KEY marker blocked by trigger');
end $$;

do $$
declare caught boolean := false;
begin
  begin
    insert into fleet_config(key, value) values ('DEPLOY_TOKEN', 'should_be_blocked');
  exception when others then caught := true;
  end;
  perform _assert(caught, '9: DEPLOY_ + TOKEN marker blocked by trigger');
end $$;

-- 10. Policy extensibility: adding a custom allow_exact rule takes effect immediately
do $$
declare pid uuid;
begin
  select id into pid from config_policies where name = 'fleet_safety';
  insert into config_rules(policy_id, rule_type, pattern, priority, note)
  values (pid, 'allow_exact', 'CUSTOM_SAFE_VAR', 100, 'acceptance test — rolled back')
  on conflict (policy_id, rule_type, pattern) do nothing;

  perform _assert(validate_config_key('CUSTOM_SAFE_VAR'), '10: exact-match rule allows custom key');
  perform _assert(not validate_config_key('CUSTOM_SAFE_VAR_EXTRA'), '10: exact match is not a prefix match');
end $$;

-- 11. validate_config_key is case-insensitive
select _assert(validate_config_key('orch_auto_pull'),  '11: lowercase safe key allowed');
select _assert(not validate_config_key('my_api_key'), '11: lowercase unsafe key denied');

-- cleanup and commit
drop function _assert(boolean, text);

rollback;

select 'acceptance_config_policies: all assertions passed' as status;

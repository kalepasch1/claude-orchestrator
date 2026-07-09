-- Rule evaluation functions for config key safety.
-- Mirrors fleet_control._safe_key(): deny runs first, then allow-prefix/allow-exact.

-- Internal: evaluate key against one specific policy.
-- deny_contains rules short-circuit to FALSE; allow rules short-circuit to TRUE; default FALSE.
create or replace function check_config_key_against_policy(p_key text, p_policy_id uuid)
returns boolean language plpgsql stable as $$
declare
  ku   text := upper(p_key);
  rule record;
begin
  for rule in
    select pattern
    from   config_rules
    where  policy_id = p_policy_id
    and    rule_type = 'deny_contains'
    order  by priority, pattern
  loop
    if ku like '%' || upper(rule.pattern) || '%' then
      return false;
    end if;
  end loop;

  for rule in
    select rule_type, pattern
    from   config_rules
    where  policy_id = p_policy_id
    and    rule_type in ('allow_prefix', 'allow_exact')
    order  by priority, pattern
  loop
    if rule.rule_type = 'allow_prefix' and ku like upper(rule.pattern) || '%' then
      return true;
    end if;
    if rule.rule_type = 'allow_exact' and ku = upper(rule.pattern) then
      return true;
    end if;
  end loop;

  return false;
end $$;

-- Public: validate a single key against the first active policy.
-- SECURITY DEFINER so callers without table access can still call via RPC.
-- Returns true if safe, false if rejected. Returns true if no active policy exists.
create or replace function validate_config_key(p_key text)
returns boolean language plpgsql stable security definer as $$
declare
  active_policy uuid;
begin
  select id into active_policy
  from   config_policies
  where  is_active = true
  order  by created_at
  limit  1;

  if active_policy is null then
    return true;
  end if;

  return check_config_key_against_policy(p_key, active_policy);
end $$;

-- Public: validate all keys in a JSONB map; returns rejected key names (empty = all OK).
-- Useful for bulk pre-flight checks before attempting writes.
create or replace function apply_config_policy(p_config jsonb)
returns text[] language plpgsql stable security definer as $$
declare
  k   text;
  bad text[] := '{}';
begin
  for k in select jsonb_object_keys(p_config) loop
    if not validate_config_key(k) then
      bad := array_append(bad, k);
    end if;
  end loop;
  return bad;
end $$;

select '0039_create_config_rule_functions OK' as status;

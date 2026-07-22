-- Suppress stale release_train failure spam from old runners.
--
-- Updated release_train writes tagged notes like "[gate:qa] ..."; legacy runners insert
-- untagged "staging QA/BUILD red" rows with blank/null to_sha every 10 minutes. Returning NULL
-- from this BEFORE INSERT trigger drops only that legacy churn while preserving current gate rows.

create or replace function public.suppress_legacy_release_churn()
returns trigger
language plpgsql
as $$
begin
  if new.deploy_status = 'failed'
     and left(coalesce(new.note, ''), 6) <> '[gate:'
     and coalesce(new.to_sha, '') = ''
     and (
       coalesce(new.note, '') like 'staging QA failed%'
       or coalesce(new.note, '') like 'staging BUILD red%'
     )
  then
    return null;
  end if;

  return new;
end;
$$;

drop trigger if exists trg_suppress_legacy_release_churn on public.releases;

create trigger trg_suppress_legacy_release_churn
before insert on public.releases
for each row
execute function public.suppress_legacy_release_churn();

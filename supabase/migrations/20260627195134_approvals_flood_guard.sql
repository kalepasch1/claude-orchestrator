-- Defense-in-depth: a DB trigger that makes an approval flood IMPOSSIBLE regardless of code bugs.
-- (1) dedup: skip a pending approval whose (project,title-prefix) already exists in the last 10 min.
-- (2) global backstop: skip inserts if >40 approvals were created in the last minute.
create or replace function approvals_flood_guard() returns trigger as $$
declare recent int;
begin
  if NEW.status is null or NEW.status = 'pending' then
    select count(*) into recent from approvals
      where status='pending'
        and coalesce(project,'') = coalesce(NEW.project,'')
        and left(title,40) = left(NEW.title,40)
        and created_at > now() - interval '10 minutes';
    if recent > 0 then return null; end if;

    select count(*) into recent from approvals where created_at > now() - interval '1 minute';
    if recent > 40 then return null; end if;
  end if;
  return NEW;
end; $$ language plpgsql;

drop trigger if exists trg_approvals_flood_guard on approvals;
create trigger trg_approvals_flood_guard before insert on approvals
  for each row execute function approvals_flood_guard();;

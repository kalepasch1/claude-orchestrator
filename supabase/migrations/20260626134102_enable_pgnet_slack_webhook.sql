
-- Enable pg_net for HTTP calls from triggers
create extension if not exists pg_net;

-- Webhook: fire slack-notify on every new pending approval
create or replace function notify_slack_on_approval()
returns trigger language plpgsql as $$
begin
  if new.status = 'pending' then
    perform net.http_post(
      url     := 'https://eatfwdzfurujcuwlhdgj.supabase.co/functions/v1/slack-notify',
      headers := '{"Content-Type":"application/json"}'::jsonb,
      body    := to_jsonb(new)
    );
  end if;
  return new;
end;
$$;

drop trigger if exists trg_slack_notify on approvals;
create trigger trg_slack_notify
  after insert on approvals
  for each row execute procedure notify_slack_on_approval();
;

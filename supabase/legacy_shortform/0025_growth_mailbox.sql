-- 0025_growth_mailbox.sql — per-app sending mailboxes (Gmail/Outlook) so outreach + replies route
-- through real inboxes into Smarter (no transactional-email vendor needed). Idempotent.
-- (Already applied to prod; this file is the version-controlled record.)
create table if not exists growth_mailbox (
  app text primary key,
  provider text not null default 'gmail',      -- gmail | outlook
  address text not null,
  oauth_account_ref text,                       -- points at Smarter's stored OAuth account
  status text not null default 'pending',       -- pending | connected | disabled
  daily_send_cap int not null default 50,
  sent_today int not null default 0,
  created_at timestamptz not null default now()
);
create or replace function mailbox_for(p_app text)
returns growth_mailbox language sql stable as $$
  select * from growth_mailbox where app = p_app and status='connected' limit 1;
$$;
alter table growth_mailbox enable row level security;
drop policy if exists growth_mailbox_sel on growth_mailbox;
create policy growth_mailbox_sel on growth_mailbox for select to authenticated using (true);
drop policy if exists growth_mailbox_ins on growth_mailbox;
create policy growth_mailbox_ins on growth_mailbox for insert to authenticated with check (true);
drop policy if exists growth_mailbox_upd on growth_mailbox;
create policy growth_mailbox_upd on growth_mailbox for update to authenticated using (true) with check (true);
grant execute on function mailbox_for(text) to authenticated, service_role;
insert into growth_mailbox(app, provider, address, status) values
 ('apparently','gmail','', 'pending'),
 ('tomorrow','gmail','', 'pending'),
 ('smarter','gmail','', 'pending')
on conflict (app) do nothing;

create table if not exists committees (
  name text primary key, mandate text, focus text,
  weight numeric default 1.0,               -- how heavily this committee counts in the aggregate
  active boolean default true, created_at timestamptz default now()
);
create table if not exists committee_reviews (
  id uuid primary key default gen_random_uuid(),
  subject_type text,                         -- proposal | decision | app | model_choice
  subject_id uuid, subject_title text,
  committee text, verdict text,              -- support | oppose | conditional | needs-info
  score numeric,                             -- 0-10 conviction
  opportunity text, risk text, recommendation text,
  created_at timestamptz default now()
);
create index if not exists idx_cr_subject on committee_reviews(subject_type, subject_id);

insert into committees (name, mandate, focus) values
 ('Legal & Compliance','Protect the business legally; flag regulated activity, IP, ToS, privacy, licensing.','legal'),
 ('Business Development & Marketing','Maximize growth, positioning, GTM, partnerships, and demand.','gtm'),
 ('Finance & Unit Economics','Guard margins, pricing, LTV/CAC, burn, and capital efficiency.','finance'),
 ('Product & UX','Ensure it delights users and solves a real, sharp problem.','product'),
 ('Security & Trust','Protect users/data; flag attack surface, auth, secrets, abuse.','security'),
 ('Growth & Experimentation','Design the fastest test to validate impact before full build.','growth'),
 ('Risk & Devil''s Advocate','Argue the strongest case AGAINST; surface hidden downside.','risk')
on conflict (name) do nothing;;

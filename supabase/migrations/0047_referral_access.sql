-- Invite-only Madeus admission. Raw referral and grant tokens are never stored.
create table if not exists orchestrator_referral_codes (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  code_hash text not null unique,
  label text,
  max_uses integer not null default 3 check (max_uses between 1 and 100),
  use_count integer not null default 0 check (use_count >= 0),
  status text not null default 'active' check (status in ('active','revoked','exhausted')),
  expires_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists orchestrator_access_grants (
  id uuid primary key default gen_random_uuid(),
  referral_code_id uuid not null references orchestrator_referral_codes(id) on delete cascade,
  token_hash text not null unique,
  status text not null default 'issued' check (status in ('issued','claimed','expired','revoked')),
  expires_at timestamptz not null,
  claimed_by uuid references auth.users(id) on delete set null,
  claimed_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists orchestrator_access_requests (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  explanation text not null check (char_length(explanation) between 80 and 3000),
  status text not null default 'pending' check (status in ('pending','approved','denied','withdrawn')),
  review_notes text,
  reviewed_by uuid references auth.users(id) on delete set null,
  reviewed_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists orchestrator_referral_codes_owner_idx on orchestrator_referral_codes(owner_user_id, status);
create index if not exists orchestrator_access_grants_expiry_idx on orchestrator_access_grants(status, expires_at);
create index if not exists orchestrator_access_requests_review_idx on orchestrator_access_requests(status, created_at desc);

alter table orchestrator_referral_codes enable row level security;
alter table orchestrator_access_grants enable row level security;
alter table orchestrator_access_requests enable row level security;

comment on table orchestrator_referral_codes is 'Hashed, revocable member referral codes. Service-role access only.';
comment on table orchestrator_access_grants is 'Short-lived, one-time admission grants issued after referral verification.';
comment on table orchestrator_access_requests is 'Invite-exemption requests awaiting operator review.';

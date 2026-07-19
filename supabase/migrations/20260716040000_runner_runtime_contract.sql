-- Fleet records are versioned so a stale daemon cannot silently claim work
-- against an incompatible in-memory executor contract.
alter table public.runner_heartbeats
  add column if not exists code_sha text,
  add column if not exists contract_hash text,
  add column if not exists contract_version text;

create index if not exists runner_heartbeats_contract_seen_idx
  on public.runner_heartbeats (hostname, contract_hash, last_seen desc);

-- 20260806120000_remediation_log.sql
-- Operator surface for the bounded remediation layer (runner/remediation_bots.py).
--
-- One table. Every action, every skip and every no-op cycle writes a row, so
-- "the bot had nothing to do" is distinguishable from "the bot is not running".
-- The previous self-healer had no such row, which is why a 17-day release
-- outage looked exactly like an idle queue.

create table if not exists remediation_log (
  id              bigserial primary key,
  ts              timestamptz not null default now(),
  remediator      text        not null,
  -- Stable identifier for the PROBLEM, not the occurrence: the attempt cap and
  -- the circuit breaker are both keyed on (remediator, problem_key, subject).
  problem_key     text        not null,
  subject         text        not null default '',
  action          text        not null default '',
  attempt_n       integer     not null default 0,
  outcome         text        not null
                    check (outcome in ('acted','skipped','tripped','escalated',
                                       'observed','heartbeat','failed')),
  -- The signal BEFORE acting and the SAME signal re-measured AFTER. A row may
  -- only be read as a success when evidence_after shows the signal cleared;
  -- dispatching the action is not evidence.
  evidence_before jsonb,
  evidence_after  jsonb,
  mode            text        not null default 'observe',
  detail          text
);

alter table remediation_log add column if not exists mode text not null default 'observe';
alter table remediation_log add column if not exists detail text;
alter table remediation_log add column if not exists evidence_before jsonb;
alter table remediation_log add column if not exists evidence_after jsonb;

create index if not exists remediation_log_ts_idx
  on remediation_log (ts desc);
-- The attempt-cap and breaker lookups: (remediator, problem_key, subject) over a window.
create index if not exists remediation_log_key_idx
  on remediation_log (remediator, problem_key, subject, ts desc);
create index if not exists remediation_log_outcome_idx
  on remediation_log (outcome, ts desc);

comment on table remediation_log is
  'Bounded remediation layer audit trail. Attempt counters and circuit-breaker '
  'state are DERIVED from these rows, so a process restart cannot reset them.';

-- The one query an operator must be able to answer:
-- "what did the bots do in the last 24h, and what did they give up on?"
create or replace view remediation_last_24h as
select
  r.remediator,
  r.problem_key,
  count(*)                                            as rows_written,
  count(*) filter (where r.outcome = 'acted')         as acted,
  count(*) filter (where r.outcome = 'observed')      as would_have_acted,
  count(*) filter (where r.outcome = 'skipped')       as skipped,
  count(*) filter (where r.outcome = 'failed')        as failed,
  -- Gave up: the breaker tripped, or the attempt cap sent it to an operator.
  count(*) filter (where r.outcome = 'tripped')       as tripped,
  count(*) filter (where r.outcome = 'escalated')     as escalated,
  count(*) filter (where r.outcome = 'heartbeat')     as heartbeats,
  max(r.ts)                                           as last_seen,
  array_agg(distinct r.subject)
    filter (where r.outcome in ('tripped','escalated')) as gave_up_on
from remediation_log r
where r.ts > now() - interval '24 hours'
group by r.remediator, r.problem_key
order by tripped desc, escalated desc, acted desc;

comment on view remediation_last_24h is
  'What the remediation bots did in the last 24h and what they gave up on. '
  'A remediator with heartbeats and no other rows is running and idle; a '
  'remediator absent from this view entirely is NOT running.';

-- CAUSAL OUTCOME FEEDBACK: traces remediation outcomes back to triggering bottleneck signals,
-- enabling the orchestrator to learn which remediation actions reduce/eliminate specific bottlenecks.
--
-- Schema: (id, bottleneck_id, remediation_slug, signal_before, signal_after, outcome_metric,
--          confidence_0to1, created_at)
--
-- The feedback table stores (timestamp, bottleneck_id, remediation_action, pre_signal, post_signal,
-- confidence_score) tuples. This enables:
--   1. Correlating which remediation actions reduced/eliminated specific measured bottlenecks
--   2. Learning which bottleneck-to-action mappings are causally effective vs spurious
--   3. Reinforcing successful remediation patterns in the orchestrator's loop control
--   4. Deferring or escalating patterns that don't improve the measured signal

create table if not exists public.causal_feedback (
  id uuid primary key default gen_random_uuid(),
  bottleneck_id uuid,                        -- reference to orch_bottlenecks.id or key
  bottleneck_key text,                       -- e.g., "cycle_time_hours", "queue_backlog_ratio"
  remediation_slug text not null,            -- task slug that attempted remediation (e.g., "improve-cycle-time")
  signal_before numeric,                     -- metric value before remediation (e.g., 96.4)
  signal_after numeric,                      -- metric value after remediation (e.g., 42.1)
  outcome_metric text,                       -- which metric improved (e.g., "cycle_time_hours")
  delta_pct numeric,                         -- ((signal_before - signal_after) / signal_before) * 100
  task_id uuid,                              -- reference to tasks.id for this remediation
  proof_id uuid,                             -- reference to execution_proof_envelopes.id if verified
  outcome_status text check (outcome_status in ('positive','neutral','negative','pending')),
  confidence_0to1 numeric check (confidence_0to1 >= 0 and confidence_0to1 <= 1),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  metadata jsonb default '{}'::jsonb         -- additional context (model used, attempt count, etc.)
);

create index if not exists idx_causal_bottleneck on public.causal_feedback(bottleneck_key, outcome_status);
create index if not exists idx_causal_remediation on public.causal_feedback(remediation_slug, created_at desc);
create index if not exists idx_causal_task on public.causal_feedback(task_id);
create index if not exists idx_causal_confidence on public.causal_feedback(confidence_0to1 desc, created_at desc);
create index if not exists idx_causal_outcome_status on public.causal_feedback(outcome_status, created_at desc);

-- ROUTE WEIGHTING: router can query high-confidence positive outcomes to reinforce actions
create or replace function causal_feedback_for_bottleneck(bottleneck_key_in text, confidence_floor numeric default 0.8)
returns table (
  remediation_slug text,
  positive_count bigint,
  neutral_count bigint,
  negative_count bigint,
  avg_confidence numeric,
  avg_delta_pct numeric
) as $$
  select
    remediation_slug,
    count(*) filter (where outcome_status='positive') as positive_count,
    count(*) filter (where outcome_status='neutral') as neutral_count,
    count(*) filter (where outcome_status='negative') as negative_count,
    round(avg(confidence_0to1)::numeric, 3) as avg_confidence,
    round(avg(delta_pct)::numeric, 2) as avg_delta_pct
  from public.causal_feedback
  where bottleneck_key = bottleneck_key_in
    and confidence_0to1 >= confidence_floor
  group by remediation_slug
  order by avg_confidence desc, positive_count desc
$$ language sql;

-- AUDIT: surface all feedback for a specific remediation slug
create or replace function causal_feedback_for_remediation(slug_in text)
returns table (
  id uuid,
  bottleneck_key text,
  signal_before numeric,
  signal_after numeric,
  outcome_status text,
  confidence_0to1 numeric,
  delta_pct numeric,
  created_at timestamptz
) as $$
  select id, bottleneck_key, signal_before, signal_after, outcome_status, confidence_0to1, delta_pct, created_at
  from public.causal_feedback
  where remediation_slug = slug_in
  order by created_at desc
$$ language sql;

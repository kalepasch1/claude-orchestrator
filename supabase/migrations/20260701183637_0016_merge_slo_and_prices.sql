-- merge-rate SLO: throughput commitment per app (merges/day the governor tries to hold)
alter table cost_slos add column if not exists target_merges_per_day numeric;

-- live provider price/quality frontier for arbitrage (updated by price_arbitrage.py)
create table if not exists provider_prices (
  provider text not null,
  model    text not null,
  usd_per_mtok_in  numeric,
  usd_per_mtok_out numeric,
  avg_quality numeric,          -- rolling quality from app_operations reviews
  updated_at timestamptz default now(),
  primary key (provider, model)
);

-- autoscale signals (append-only): when demand exceeds fleet capacity
create table if not exists autoscale_signals (
  id uuid primary key default gen_random_uuid(),
  queue_depth integer,
  weighted_demand numeric,
  fleet_ceiling integer,
  recommend_workers integer,
  reason text,
  created_at timestamptz default now()
);;

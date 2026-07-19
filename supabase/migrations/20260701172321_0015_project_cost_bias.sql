alter table projects add column if not exists cost_bias integer not null default 0;
-- 0=normal routing, 1=prefer cheaper tier, 2=cheapest capable only (set by cost_slo loop);

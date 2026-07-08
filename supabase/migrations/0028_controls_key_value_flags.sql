-- Explicit dashboard flags, while preserving the original pause-control shape.
alter table controls add column if not exists key text;
alter table controls add column if not exists value jsonb;

create unique index if not exists controls_key_unique
  on controls(key)
  where key is not null;

insert into controls(key, value, reason, updated_by, updated_at)
values (
  'use_purchased_credits',
  '{"enabled": false, "purpose": "Allow paid API credits when value beats subscription/local routes"}'::jsonb,
  'dashboard flag: explicit owner intent for paid credits',
  'migration',
  now()
)
on conflict (key) where key is not null do nothing;

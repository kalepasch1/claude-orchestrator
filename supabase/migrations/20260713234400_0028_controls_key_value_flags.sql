-- Explicit dashboard flags, while preserving the original pause-control shape.
-- NOTE (applied to prod, deviates from repo file): the repo migration also seeds a
-- controls row for 'use_purchased_credits' with {"enabled": false}. Prod already carries
-- that flag in the legacy shape (scope='config', project='use_purchased_credits',
-- reason='enabled'), and prod has a unique index controls_global_uniq (scope) WHERE
-- project IS NULL that the seed's default scope='global' collides with. Seeding it would
-- also take precedence in control_flags.get_bool() and silently flip the flag true->false.
-- Schema only; existing flag semantics preserved.
alter table controls add column if not exists key text;
alter table controls add column if not exists value jsonb;

create unique index if not exists controls_key_unique
  on controls(key)
  where key is not null;;

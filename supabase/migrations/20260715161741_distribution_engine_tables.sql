-- DISTRIBUTION ENGINE — grassroots, low-cost/high-impact distribution across ALL apps, run by
-- agents, with the human's time directed to only what a human can do. Idempotent, RLS default-deny.
-- Complements (does not replace) the social layer: social = owned channels; distribution = earned.

-- 1) Channels beyond social (earned/grassroots surfaces).
create table if not exists public.growth_distribution_channel (
  channel text primary key,
  display_name text not null,
  family text not null default 'community',      -- community | directory | content | partnership | event | media | referral | outbound
  cost_level text not null default 'free',        -- free | low | medium
  runner text not null default 'agent',           -- agent | human | hybrid  (who executes)
  typical_cycle_days int not null default 7,
  notes text,
  enabled boolean not null default true
);

-- 2) Grassroots play library (reusable, per-channel campaigns with agent + human steps).
create table if not exists public.growth_distribution_play (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name text not null,
  channel text not null references public.growth_distribution_channel(channel),
  objective text not null default 'awareness',     -- awareness | signups | credibility | partnership
  app_scope text not null default 'any',           -- 'any' or a specific app
  agent_steps jsonb not null default '[]'::jsonb,   -- what the bots do autonomously
  human_steps jsonb not null default '[]'::jsonb,   -- what only the human can do (specific + detailed)
  cost_usd numeric not null default 0,
  expected_reach int not null default 0,
  human_minutes int not null default 0,             -- human effort per cycle
  cycle_days int not null default 7,
  score numeric not null default 0.5,               -- proven-ness (updated by outcomes)
  status text not null default 'active',
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- 3) A running instance of a play for one app.
create table if not exists public.growth_distribution_run (
  id uuid primary key default gen_random_uuid(),
  play_id uuid references public.growth_distribution_play(id),
  app text not null,
  mode text not null default 'approval',            -- off | approval | auto
  status text not null default 'active',
  outcome_score numeric not null default 0,
  metrics jsonb not null default '{}'::jsonb,       -- reach, clicks, signups, cost
  created_at timestamptz not null default now()
);
create index if not exists idx_gdr_app on public.growth_distribution_run(app);

-- 4) THE HUMAN TASK ENGINE — specific, evidence-backed, highest-EV asks of the human.
create table if not exists public.growth_human_task (
  id uuid primary key default gen_random_uuid(),
  app text not null,
  run_id uuid references public.growth_distribution_run(id) on delete set null,
  kind text not null,                               -- attend_event | call_person | record_video | intro_request
                                                    -- | podcast_pitch | community_answer | write_post | demo | speak
  title text not null,                              -- "Call Jane Doe (GC @ Ramp) — she posted about MTL licensing"
  target_label text,                                -- the specific person/event/community
  target_ref text,                                  -- profile/event/thread URL
  why text,                                         -- evidence-backed rationale
  prep jsonb not null default '{}'::jsonb,          -- dossier: talking points, script, who'll be there, what to bring
  expected_impact numeric not null default 0,       -- est. reach or signups
  effort_minutes int not null default 30,
  ev_per_hour numeric generated always as (
    case when effort_minutes > 0 then round((expected_impact * 60.0) / effort_minutes, 3) else 0 end
  ) stored,
  deadline date,
  priority text not null default 'medium',
  status text not null default 'suggested',         -- suggested | accepted | scheduled | done | declined | expired
  outcome jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (app, kind, target_ref, status)
);
create index if not exists idx_ght_rank on public.growth_human_task(status, ev_per_hour desc);

-- 5) Impact per run/channel (non-link channels; link clicks stay in growth_social_link).
create table if not exists public.growth_distribution_metric (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references public.growth_distribution_run(id) on delete cascade,
  app text, channel text,
  day date not null default (now() at time zone 'utc')::date,
  reach int not null default 0, clicks int not null default 0, signups int not null default 0,
  cost_usd numeric not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists idx_gdm_run on public.growth_distribution_metric(run_id, day);

do $$ declare t text; begin
  foreach t in array array['growth_distribution_channel','growth_distribution_play','growth_distribution_run',
                           'growth_human_task','growth_distribution_metric'] loop
    execute format('alter table public.%I enable row level security;', t);
  end loop;
end $$;

-- Channel catalog seed --------------------------------------------------------
insert into public.growth_distribution_channel(channel, display_name, family, cost_level, runner, typical_cycle_days, notes) values
 ('reddit_community','Reddit / niche subreddits','community','free','hybrid',3,'Value-first answers; respect each sub''s self-promo ratio.'),
 ('hn_community','Hacker News (Show HN / comments)','community','free','hybrid',14,'Show HN is a one-shot; comment credibility compounds.'),
 ('discord_slack','Discord / Slack communities','community','free','hybrid',7,'Presence + genuine help; no drive-by links.'),
 ('forum_niche','Niche forums & Q&A','community','free','agent',7,'Long-tail SEO value from answers.'),
 ('product_hunt','Product Hunt / launch directories','directory','free','hybrid',30,'One-shot spike; needs a hunter + day-of human push.'),
 ('directory_blitz','App/SaaS directories','directory','free','agent',30,'Long-tail, cheap, compounding backlinks.'),
 ('seo_content','Programmatic + pillar SEO','content','free','agent',30,'Compounding; slow start, highest terminal value.'),
 ('build_in_public','Build-in-public narrative','content','free','hybrid',3,'Founder-led; the human IS the moat.'),
 ('newsletter_swap','Newsletter swaps / features','partnership','free','hybrid',14,'Borrow trust from an aligned list.'),
 ('partnership','Integration & referral partners','partnership','free','human',30,'Highest-leverage, needs a human relationship.'),
 ('conference','Conferences & meetups','event','medium','human',30,'Hallway track > booth. Human-only.'),
 ('podcast','Podcast guest circuit','media','free','hybrid',14,'Borrowed audience + evergreen authority.'),
 ('creator_seeding','Creator / micro-influencer seeding','media','low','hybrid',14,'Niche creators outperform reach at launch.'),
 ('referral_waitlist','Referral loops & waitlist','referral','free','agent',7,'Turns each signup into distribution.'),
 ('warm_intro','Warm intros from the network','outbound','free','human',7,'Highest conversion; only the human can ask.')
on conflict (channel) do update set display_name=excluded.display_name, family=excluded.family,
  cost_level=excluded.cost_level, runner=excluded.runner, notes=excluded.notes;;

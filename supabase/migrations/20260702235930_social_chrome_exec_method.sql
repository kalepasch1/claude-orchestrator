-- Chrome execution path: let posts/actions run by driving the user's logged-in browser via
-- Claude-in-Chrome (a Cowork "browser worker" task) instead of official APIs. Idempotent.

alter table public.growth_channel_account add column if not exists exec_method text not null default 'api'; -- api | chrome | auto
alter table public.growth_social_post   add column if not exists exec_method text;  -- inherits account default when null
alter table public.growth_social_action add column if not exists exec_method text;

-- Per-platform browser recipes (how the browser worker performs each action). Kept in the DB so
-- ops can tune selectors without a redeploy; the worker also has code defaults.
create table if not exists public.growth_browser_recipe (
  platform text not null,
  action text not null,                    -- post | article | thread | comment | like | connect | follow
  url_template text,                        -- where to go (e.g. https://www.linkedin.com/feed/)
  steps jsonb not null default '[]'::jsonb, -- ordered UI steps: [{do, selector|text|hint}]
  login_check jsonb not null default '{}'::jsonb, -- {url, logged_in_hint, logged_out_hint}
  enabled boolean not null default true,
  updated_at timestamptz not null default now(),
  primary key (platform, action)
);
alter table public.growth_browser_recipe enable row level security;

-- Resolve the effective execution method for an item (item override → account default).
create or replace function public.effective_exec_method(p_account_id uuid, p_override text)
returns text language sql stable as $$
  select coalesce(p_override, (select exec_method from public.growth_channel_account where id=p_account_id), 'api');
$$;

-- Worker pull for the CHROME path: everything queued/scheduled+due that resolves to chrome exec,
-- regardless of autonomy (queued means auto-queued OR human-approved). Returns login recipe too.
create or replace function public.social_due_chrome(p_app text default null, p_limit int default 25)
returns jsonb language plpgsql as $$
declare posts jsonb; acts jsonb;
begin
  select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) into posts from (
    select p.id, p.app, p.account_id, p.platform, p.kind, p.title, p.body, p.hashtags, p.scheduled_at,
           a.handle, a.owner,
           (select to_jsonb(r) from public.growth_browser_recipe r where r.platform=p.platform and r.action=p.kind limit 1) as recipe
    from public.growth_social_post p join public.growth_channel_account a on a.id=p.account_id
    where p.status in ('scheduled','queued')
      and (p.scheduled_at is null or p.scheduled_at <= now())
      and public.effective_exec_method(p.account_id, p.exec_method)='chrome'
      and (p_app is null or p.app=p_app)
    order by p.scheduled_at nulls first limit p_limit) x;
  select coalesce(jsonb_agg(to_jsonb(y)),'[]'::jsonb) into acts from (
    select s.id, s.app, s.account_id, s.platform, s.action, s.target_ref, s.target_label, s.payload,
           a.handle, a.owner,
           (select to_jsonb(r) from public.growth_browser_recipe r where r.platform=s.platform and r.action=s.action limit 1) as recipe
    from public.growth_social_action s join public.growth_channel_account a on a.id=s.account_id
    where s.status='queued'
      and (s.scheduled_at is null or s.scheduled_at <= now())
      and public.effective_exec_method(s.account_id, s.exec_method)='chrome'
      and (p_app is null or s.app=p_app)
    order by s.created_at limit p_limit) y;
  return jsonb_build_object('posts', posts, 'actions', acts);
end $$;;

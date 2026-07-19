-- SIGNUP ATTRIBUTION — closes the loop: every app posts its signup event, we attribute it to the
-- channel/link/run that earned it, which makes CAC real and feeds score_distribution_runs ->
-- play scores -> recommend_distribution. Idempotent per (app, external_user_ref).

create table if not exists public.growth_signup_event (
  id uuid primary key default gen_random_uuid(),
  app text not null,
  external_user_ref text not null,          -- the app's own user id (never PII-required)
  channel text,                              -- distribution channel if known
  source_ref text,                           -- url/thread/event that earned it
  slug text,                                 -- tracked-link slug if it came through one
  campaign text,
  revenue numeric not null default 0,
  attributed_to text,                        -- resolved: 'link:<slug>' | 'channel:<c>' | 'direct'
  created_at timestamptz not null default now(),
  meta jsonb not null default '{}'::jsonb,
  unique (app, external_user_ref)
);
create index if not exists idx_signup_app_day on public.growth_signup_event(app, created_at);
alter table public.growth_signup_event enable row level security;

-- The single ingest RPC every app calls on signup. Idempotent; resolves attribution.
create or replace function public.record_signup(p jsonb)
returns jsonb language plpgsql as $$
declare v_app text; v_ref text; v_slug text; v_channel text; v_rev numeric; v_attr text; v_run uuid; existed boolean;
begin
  v_app := coalesce(p->>'app', 'unknown');
  v_ref := coalesce(p->>'external_user_ref', p->>'userRef');
  if v_ref is null then raise exception 'external_user_ref required'; end if;
  v_slug := nullif(p->>'slug','');
  v_channel := nullif(p->>'channel','');
  v_rev := coalesce((p->>'revenue')::numeric, 0);

  -- resolve the channel from the tracked link when only a slug is supplied
  if v_channel is null and v_slug is not null then
    select 'social:'||coalesce(l.platform,'unknown') into v_channel
      from public.growth_social_link l where l.slug = v_slug;
  end if;
  v_attr := case when v_slug is not null then 'link:'||v_slug
                 when v_channel is not null then 'channel:'||v_channel
                 else 'direct' end;

  insert into public.growth_signup_event(app, external_user_ref, channel, source_ref, slug, campaign, revenue, attributed_to, meta)
  values (v_app, v_ref, v_channel, p->>'source_ref', v_slug, p->>'campaign', v_rev, v_attr, coalesce(p->'meta','{}'::jsonb))
  on conflict (app, external_user_ref) do nothing;
  get diagnostics existed = row_count;
  if not existed then
    return jsonb_build_object('recorded', false, 'reason', 'already_counted', 'app', v_app, 'ref', v_ref);
  end if;

  -- credit the tracked link (organic/social attribution + revenue)
  if v_slug is not null then perform public.record_link_conversion(v_slug, v_rev); end if;

  -- credit the distribution run for that channel (makes CAC + play scoring real)
  if v_channel is not null then
    select dr.id into v_run from public.growth_distribution_run dr
      join public.growth_distribution_play pl on pl.id = dr.play_id
     where dr.app = v_app and dr.status='active' and pl.channel = replace(v_channel,'social:','')
     limit 1;
    insert into public.growth_distribution_metric(run_id, app, channel, signups, cost_usd)
    values (v_run, v_app, v_channel, 1, 0);
  end if;

  return jsonb_build_object('recorded', true, 'app', v_app, 'attributed_to', v_attr, 'run_id', v_run, 'revenue', v_rev);
end $$;

-- Unified attribution: what actually earned signups, across links + distribution channels.
create or replace function public.attribution_rollup(p_app text default null)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'by_attribution', coalesce((
      select jsonb_agg(to_jsonb(a) order by a.signups desc) from (
        select coalesce(attributed_to,'direct') attributed_to, count(*) signups, round(sum(revenue),2) revenue
        from public.growth_signup_event where (p_app is null or app=p_app) group by 1) a), '[]'::jsonb),
    'by_channel', coalesce((
      select jsonb_agg(to_jsonb(c) order by c.signups desc) from (
        select coalesce(channel,'direct') channel, count(*) signups, round(sum(revenue),2) revenue
        from public.growth_signup_event where (p_app is null or app=p_app) group by 1) c), '[]'::jsonb),
    'distribution_channels', public.distribution_rollup(p_app),
    'totals', (select jsonb_build_object('signups', count(*), 'revenue', round(coalesce(sum(revenue),0),2))
               from public.growth_signup_event where (p_app is null or app=p_app))
  );
$$;

insert into public.growth_settings(key, value) values
 ('social_version','v29-network-graph+signup-attribution'),
 ('network_rpcs','compute_relationship_strength,rank_warm_intro_targets,generate_warm_intro_tasks,record_signup,attribution_rollup'),
 ('signup_contract','POST record_signup({app, external_user_ref, slug?, channel?, source_ref?, revenue?}) — idempotent per (app,external_user_ref)')
on conflict (key) do update set value=excluded.value;;

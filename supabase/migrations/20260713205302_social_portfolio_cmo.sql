-- Portfolio CMO: allocate a shared marketing budget across ALL apps by blended organic+paid ROI.
-- Reads organic conversions/revenue (growth_social_link) + paid spend/revenue (growth_ad_spend,
-- last 30d) per app, computes a return-per-effort index, and suggests a budget share.
create or replace function public.portfolio_cmo(p_budget numeric default 1000)
returns jsonb language plpgsql stable as $$
declare out jsonb; total_roi numeric;
begin
  create temp table _cmo on commit drop as
  select a.app,
    (select count(*) from public.growth_social_post p where p.app=a.app and p.status='posted') organic_posts,
    coalesce((select sum(conversions) from public.growth_social_link l where l.app=a.app),0) organic_conv,
    coalesce((select sum(revenue) from public.growth_social_link l where l.app=a.app),0) organic_rev,
    coalesce((select sum(spend) from public.growth_ad_spend s where s.app=a.app and s.day > (now()-interval '30 days')::date),0) paid_spend,
    coalesce((select sum(revenue) from public.growth_ad_spend s where s.app=a.app and s.day > (now()-interval '30 days')::date),0) paid_rev,
    coalesce((select sum(conversions) from public.growth_ad_spend s where s.app=a.app and s.day > (now()-interval '30 days')::date),0) paid_conv
  from (select distinct app from public.growth_channel_account) a;

  -- return per unit effort: (all revenue) / (paid $ + organic effort proxy); +1 avoids div0.
  update _cmo set app=app;  -- noop to keep temp table
  select sum(t.roi) into total_roi from (
    select (organic_rev + paid_rev) / greatest(paid_spend + organic_posts, 1) roi from _cmo) t;

  select coalesce(jsonb_agg(to_jsonb(r) order by r.roi_index desc),'[]'::jsonb) into out from (
    select app, organic_posts, organic_conv, round(organic_rev,2) organic_rev,
      round(paid_spend,2) paid_spend, round(paid_rev,2) paid_rev, paid_conv,
      round((organic_rev + paid_rev) / greatest(paid_spend + organic_posts,1), 4) roi_index,
      round(((organic_rev + paid_rev) / greatest(paid_spend + organic_posts,1)) / greatest(total_roi,0.0001), 4) suggested_share,
      round(p_budget * ((organic_rev + paid_rev) / greatest(paid_spend + organic_posts,1)) / greatest(total_roi,0.0001), 2) suggested_budget
    from _cmo
  ) r;
  return jsonb_build_object('budget', p_budget, 'allocations', out,
    'note', 'Marginal-ROI split across apps (organic+paid). Zero-history apps get an exploration floor via the equal-effort denominator.');
end $$;

-- Per-app channel ROI (organic vs paid) for the paid+organic bandit view.
create or replace function public.channel_roi(p_app text default null)
returns jsonb language plpgsql stable as $$
declare out jsonb;
begin
  select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) into out from (
    select 'organic'::text channel, count(*) filter (where true) n,
      coalesce(sum(l.conversions),0) conversions, coalesce(sum(l.revenue),0) revenue, 0::numeric spend
    from public.growth_social_link l where (p_app is null or l.app=p_app)
    union all
    select 'paid', count(*), coalesce(sum(s.conversions),0), coalesce(sum(s.revenue),0), coalesce(sum(s.spend),0)
    from public.growth_ad_spend s where (p_app is null or s.app=p_app) and s.day > (now()-interval '30 days')::date
  ) x;
  return out;
end $$;

insert into public.growth_settings(key, value) values
 ('social_version','v27-safety-gate+portfolio-cmo'),
 ('marketing_control_rpcs','marketing_control_status,set_send_gate,approve_send,send_gate_active,portfolio_cmo,channel_roi,social_northstar')
on conflict (key) do update set value=excluded.value;;

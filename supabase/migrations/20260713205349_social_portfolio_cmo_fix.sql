create or replace function public.portfolio_cmo(p_budget numeric default 1000)
returns jsonb language sql stable as $$
  with base as (
    select a.app,
      (select count(*) from public.growth_social_post p where p.app=a.app and p.status='posted') organic_posts,
      coalesce((select sum(conversions) from public.growth_social_link l where l.app=a.app),0) organic_conv,
      coalesce((select sum(revenue) from public.growth_social_link l where l.app=a.app),0) organic_rev,
      coalesce((select sum(spend) from public.growth_ad_spend s where s.app=a.app and s.day>(now()-interval '30 days')::date),0) paid_spend,
      coalesce((select sum(revenue) from public.growth_ad_spend s where s.app=a.app and s.day>(now()-interval '30 days')::date),0) paid_rev,
      coalesce((select sum(conversions) from public.growth_ad_spend s where s.app=a.app and s.day>(now()-interval '30 days')::date),0) paid_conv
    from (select distinct app from public.growth_channel_account) a
  ), roi as (
    select *, (organic_rev+paid_rev)/greatest(paid_spend+organic_posts,1) roi_index from base
  ), tot as (select greatest(sum(roi_index),0.0001) t from roi)
  select jsonb_build_object('budget', p_budget, 'allocations',
    coalesce(jsonb_agg(jsonb_build_object(
      'app', app, 'organic_posts', organic_posts, 'organic_conv', organic_conv, 'organic_rev', round(organic_rev,2),
      'paid_spend', round(paid_spend,2), 'paid_rev', round(paid_rev,2), 'paid_conv', paid_conv,
      'roi_index', round(roi_index,4), 'suggested_share', round(roi_index/(select t from tot),4),
      'suggested_budget', round(p_budget*roi_index/(select t from tot),2)) order by roi_index desc), '[]'::jsonb),
    'note', 'Marginal-ROI split across apps (organic+paid); zero-history apps get an equal-effort exploration floor.')
  from roi;
$$;;

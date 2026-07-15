-- Wave 2/3 DB objects that were queued but never applied. Additive, idempotent, RLS default-deny.

-- Predictive posting: best hour-of-day for an account from its historical engagement.
create or replace function public.best_post_slot(p_account_id uuid, p_platform text default null)
returns timestamptz language plpgsql stable as $$
declare best_hour int; total int; base timestamptz;
begin
  select count(*) into total from public.growth_social_post
   where account_id=p_account_id and status='posted' and metrics ? 'impressions';
  if coalesce(total,0) < 8 then
    return now() + make_interval(mins => 30 + floor(random()*180)::int);  -- not enough data → soon+jitter
  end if;
  select h into best_hour from (
    select extract(hour from updated_at)::int h,
      avg((coalesce((metrics->>'likes')::numeric,0)+coalesce((metrics->>'comments')::numeric,0)
          +coalesce((metrics->>'shares')::numeric,0)+coalesce((metrics->>'clicks')::numeric,0))
          / greatest(coalesce((metrics->>'impressions')::numeric,0),1)) r
    from public.growth_social_post
    where account_id=p_account_id and status='posted' and metrics ? 'impressions'
    group by 1 order by r desc nulls last limit 1) t;
  base := date_trunc('day', now()) + make_interval(hours => coalesce(best_hour,10));
  if base <= now() then base := base + interval '1 day'; end if;
  return base + make_interval(mins => floor(random()*20)::int);
end $$;

-- Attribution: record a conversion + revenue on a tracked link (webhook target per app).
create or replace function public.record_link_conversion(p_slug text, p_revenue numeric default 0)
returns void language plpgsql as $$
begin
  update public.growth_social_link
     set conversions = conversions + 1, revenue = revenue + coalesce(p_revenue,0)
   where slug = p_slug;
end $$;

-- North-star: answered-from-strategy rate (quality-passed → conversion) per app.
create or replace function public.social_northstar(p_app text default null)
returns jsonb language plpgsql stable as $$
declare pub numeric; qpass numeric; conv numeric; rev numeric;
begin
  select count(*) into pub from public.growth_social_post where status='posted' and (p_app is null or app=p_app);
  select count(*) into qpass from public.growth_social_post
    where status='posted' and (meta->'cade'->>'band') in ('strong','defensible') and (p_app is null or app=p_app);
  select coalesce(sum(conversions),0), coalesce(sum(revenue),0) into conv, rev
    from public.growth_social_link where (p_app is null or app=p_app);
  return jsonb_build_object(
    'published', pub, 'quality_passed', qpass, 'conversions', conv, 'revenue', rev,
    'quality_pass_rate', case when pub>0 then round(qpass/pub,4) else 0 end,
    'answered_from_strategy_rate', case when pub>0 then round(conv/pub,4) else 0 end);
end $$;

-- ICP-aware marketplace ranking (additive; existing rank_marketplace untouched). Blends outcome
-- score with a naive keyword overlap between the ICP and each scheme's targeting/spec. The code
-- endpoint layers on synthetic-audience reception for a sharper fit score.
create or replace function public.rank_marketplace_for_icp(p_icp text default null, p_objective text default null)
returns jsonb language plpgsql stable as $$
declare out jsonb;
begin
  select coalesce(jsonb_agg(to_jsonb(s) || jsonb_build_object('fit', s.fit) order by s.fit desc, s.score desc),'[]'::jsonb) into out
  from (
    select g.*,
      round(0.7*g.score + 0.3*(
        case when p_icp is null then 0.5
             else least(1.0, (length(g.recommended_for::text) - length(replace(lower(g.recommended_for::text), lower(split_part(coalesce(p_icp,''),' ',1)), ''))) ) end
      ),4) fit
    from public.growth_scheme g
    where g.status='active' and (p_objective is null or g.objective=p_objective)
  ) s;
  return out;
end $$;;

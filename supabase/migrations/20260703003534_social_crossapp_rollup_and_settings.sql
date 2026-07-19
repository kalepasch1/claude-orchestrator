-- (7) Shared-service cross-app rollup: one marketer across every app/venture.
create or replace function public.social_rollup_all()
returns jsonb language plpgsql as $$
declare out jsonb;
begin
  select coalesce(jsonb_agg(to_jsonb(x) order by x.app),'[]'::jsonb) into out from (
    select a.app,
      count(distinct a.id) accounts,
      count(distinct a.id) filter (where a.status='connected') connected,
      (select count(*) from public.growth_social_post p where p.app=a.app and p.status='posted') posted,
      (select count(*) from public.growth_social_action s where s.app=a.app and s.status='done') engaged,
      (select round(sum(clicks),0) from public.growth_social_link l where l.app=a.app) clicks
    from public.growth_channel_account a group by a.app) x;
  return out;
end $$;

-- Register new orchestration cues (auto-amplify default OFF for safety; flip to enable swarm likes).
insert into public.growth_settings(key, value) values
 ('social_auto_amplify','false'),
 ('social_flywheel','compute_scheme_outcomes,auto_promote_schemes,assign_best_variant,next_slot_jitter,auto_amplify'),
 ('social_corpus_grounding','apparently:search_corpus_authority'),
 ('social_version','v25-flywheel+corpus+media+deliverability')
on conflict (key) do update set value=excluded.value;;

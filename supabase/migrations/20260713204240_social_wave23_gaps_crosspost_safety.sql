-- Self-writing backlog, cross-venture graph, brand-safety gate. Additive, idempotent, RLS default-deny.

-- (self-writing backlog) suggestions table + gap detector.
create table if not exists public.growth_intake_suggestion (
  id uuid primary key default gen_random_uuid(),
  kind text not null, app text, ref text, detail jsonb not null default '{}'::jsonb,
  severity text not null default 'medium', status text not null default 'new',
  created_at timestamptz not null default now(),
  unique (kind, app, ref, status)
);
alter table public.growth_intake_suggestion enable row level security;

create or replace function public.detect_social_gaps()
returns int language plpgsql as $$
declare n int := 0;
begin
  -- connected accounts with no posted content in 7 days
  insert into public.growth_intake_suggestion(kind, app, ref, detail, severity)
  select 'idle_account', a.app, a.id::text,
         jsonb_build_object('platform',a.platform,'handle',a.handle), 'high'
  from public.growth_channel_account a
  where a.status='connected'
    and not exists (select 1 from public.growth_social_post p where p.account_id=a.id and p.status='posted' and p.updated_at > now()-interval '7 days')
  on conflict (kind, app, ref, status) do nothing;
  -- drafts stuck needing generation > 48h
  insert into public.growth_intake_suggestion(kind, app, ref, detail, severity)
  select 'stuck_draft', p.app, p.id::text, jsonb_build_object('platform',p.platform), 'medium'
  from public.growth_social_post p
  where p.status='draft' and (p.meta->>'needs_generation')::boolean is true and p.created_at < now()-interval '48 hours'
  on conflict (kind, app, ref, status) do nothing;
  -- accounts in poor health
  insert into public.growth_intake_suggestion(kind, app, ref, detail, severity)
  select 'account_health', a.app, a.id::text, jsonb_build_object('status',h.status), 'high'
  from public.growth_account_health h join public.growth_channel_account a on a.id=h.account_id
  where h.status in ('watch','paused')
  on conflict (kind, app, ref, status) do nothing;
  get diagnostics n = row_count; return n;
end $$;

-- (cross-venture) audience overlap graph + sibling targets for a winning post.
create table if not exists public.growth_audience_overlap (
  app_a text not null, app_b text not null, overlap numeric not null default 0,
  updated_at timestamptz not null default now(), primary key (app_a, app_b)
);
alter table public.growth_audience_overlap enable row level security;

create or replace function public.crosspost_targets(p_post_id uuid)
returns jsonb language plpgsql stable as $$
declare pst public.growth_social_post; out jsonb;
begin
  select * into pst from public.growth_social_post where id=p_post_id;
  if not found then return '[]'::jsonb; end if;
  select coalesce(jsonb_agg(to_jsonb(x) order by x.overlap desc nulls last),'[]'::jsonb) into out from (
    select a.id account_id, a.app, a.platform, a.handle,
      coalesce((select o.overlap from public.growth_audience_overlap o
                where (o.app_a=pst.app and o.app_b=a.app) or (o.app_a=a.app and o.app_b=pst.app) limit 1), 0) overlap
    from public.growth_channel_account a
    where a.platform=pst.platform and a.app<>pst.app and a.status='connected' and a.autonomy<>'off'
  ) x;
  return out;
end $$;

-- (brand safety) per-account guardrails + pre-publish gate.
create table if not exists public.growth_brand_guardrail (
  account_id uuid primary key references public.growth_channel_account(id) on delete cascade,
  banned_terms text[] not null default '{}', required_disclosure boolean not null default false,
  max_aggressiveness text not null default 'balanced', notes text,
  updated_at timestamptz not null default now()
);
alter table public.growth_brand_guardrail enable row level security;

create or replace function public.check_publish_allowed(p_post_id uuid)
returns jsonb language plpgsql stable as $$
declare pst public.growth_social_post; g public.growth_brand_guardrail; reasons text[] := '{}'; term text;
begin
  select * into pst from public.growth_social_post where id=p_post_id;
  if not found then return jsonb_build_object('allowed', false, 'reasons', array['post_not_found']); end if;
  select * into g from public.growth_brand_guardrail where account_id=pst.account_id;
  if found then
    foreach term in array coalesce(g.banned_terms,'{}') loop
      if position(lower(term) in lower(coalesce(pst.body,'')||' '||coalesce(pst.title,''))) > 0 then
        reasons := reasons || ('banned_term:'||term);
      end if;
    end loop;
    if g.required_disclosure and (pst.meta->>'promotional')::boolean is true
       and position('#ad' in lower(coalesce(pst.body,''))) = 0 then
      reasons := reasons || 'missing_disclosure';
    end if;
  end if;
  return jsonb_build_object('allowed', array_length(reasons,1) is null, 'reasons', reasons);
end $$;

-- register the manifest of RPCs the app is expected to call (source of truth for a code↔DB verifier)
insert into public.growth_settings(key, value) values
 ('social_version','v26-wave23-applied'),
 ('social_rpc_manifest','social_enabled,social_due_now,social_due_chrome,connect_channel_account,apply_scheme,mark_social_result,schedule_social_post,enqueue_social_action,pick_variant,record_post_metrics,create_tracked_link,record_link_click,record_link_conversion,social_attribution,ingest_signal,team_amplify,set_voice_profile,record_action_health,promote_scheme_run,rank_marketplace,rank_marketplace_for_icp,compute_scheme_outcomes,auto_promote_schemes,social_rollup,social_rollup_all,tick_warmup,warmup_multiplier,next_slot,best_post_slot,social_northstar,detect_social_gaps,crosspost_targets,check_publish_allowed')
on conflict (key) do update set value=excluded.value;;

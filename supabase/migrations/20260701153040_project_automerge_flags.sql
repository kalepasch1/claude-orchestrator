-- per-project auto-merge + confidence scope (controlled rollout: tomorrow first)
alter table projects add column if not exists auto_merge boolean not null default false;
alter table projects add column if not exists confidence_threshold numeric(4,3);
-- turn ON auto-merge for tomorrow ONLY, with a lower gate so tested work merges itself
update projects set auto_merge=true, confidence_threshold=0.4 where name='tomorrow';
-- keep all others OFF (default) until the proof succeeds
-- budgets for the new QA providers (cheap caps; local/subscription are free)
insert into provider_budgets (provider, project, monthly_cap, hard_pause) values
  ('deepseek', null, 10, true), ('openai', null, 15, true), ('google', null, 10, true)
on conflict (provider, project) do nothing;
select name, auto_merge, confidence_threshold from projects order by auto_merge desc, name limit 12;;

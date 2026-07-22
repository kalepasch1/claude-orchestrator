-- Track train and deploy fate for each outcomes row so router_stats can score
-- coders by actual deployed value, not just tests-passed.
--
-- merge_train already writes train_outcome/merge_attributed_by/merged_at (fail-soft).
-- deploy_verify will write deployed/deploy_status after Vercel confirms READY.
alter table outcomes
  add column if not exists deployed            boolean default false,
  add column if not exists deploy_status       text,
  add column if not exists train_outcome       text,
  add column if not exists merge_attributed_by text,
  add column if not exists merged_at           timestamptz;

create index if not exists outcomes_deploy_idx on outcomes(project, integrated, deployed)
  where integrated = true;

alter table approvals add column if not exists cluster_key text;
create index if not exists idx_approvals_cluster on approvals(cluster_key) where status='pending';;

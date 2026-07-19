-- One pending card per (kind, title): stops the duplicate-card floods
-- (61k denied cards on 6/27 + 135 today were duplicates of a handful of issues).
-- runner's approval() already catches insert errors and skips gracefully.
create unique index if not exists approvals_one_pending_per_issue
  on approvals (kind, title) where status = 'pending';;

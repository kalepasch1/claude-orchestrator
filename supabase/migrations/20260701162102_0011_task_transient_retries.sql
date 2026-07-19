alter table tasks add column if not exists transient_retries integer not null default 0;;

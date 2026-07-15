
alter table if exists tasks add column if not exists build_fail_count int not null default 0;
alter table if exists tasks add column if not exists force_coder text;
;

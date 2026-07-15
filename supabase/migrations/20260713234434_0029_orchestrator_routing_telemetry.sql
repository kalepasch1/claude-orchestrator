-- Routing intelligence telemetry. All columns are optional so old code remains compatible.
alter table tasks add column if not exists sensitivity text;
alter table tasks add column if not exists force_coder text;
alter table tasks add column if not exists thermal_score double precision;
alter table tasks add column if not exists estimated_minutes double precision;

alter table outcomes add column if not exists diff_bytes integer;
alter table outcomes add column if not exists total_tokens integer;
alter table outcomes add column if not exists tokens_per_diff_byte double precision;
alter table outcomes add column if not exists review_failures integer;
alter table outcomes add column if not exists review_failures_per_merge double precision;
alter table outcomes add column if not exists sensitivity text;;

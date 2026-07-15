
alter table projects add column if not exists test_cmd text;
update projects set test_cmd = 'npx vue-tsc --noEmit' where name = 'smarter';
;

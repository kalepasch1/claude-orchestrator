alter table projects add column if not exists build_cmd text;   -- real prod build (auto-detected: npm run build / typecheck);

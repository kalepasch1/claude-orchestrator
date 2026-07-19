alter table public.accounts enable row level security;
-- no policies: only the service role (runner) can read/write account config; web/anon cannot.;

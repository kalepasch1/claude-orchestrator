create table if not exists surface_returns (
  surface text primary key, avg_delta numeric, n integer, updated_at timestamptz default now()
);;

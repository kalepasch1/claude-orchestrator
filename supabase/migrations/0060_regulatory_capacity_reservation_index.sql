-- 0059 encountered an existing global index name from the earlier capacity
-- network. PostgreSQL index names share a schema namespace, so ensure the new
-- reservation table receives its own unambiguous organization/status index.
create index if not exists idx_reg_capacity_reservation_org
  on public.regulatory_capacity_reservations(organization_id,status,created_at desc);

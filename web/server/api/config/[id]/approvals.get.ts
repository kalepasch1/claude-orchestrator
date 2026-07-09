// GET /api/config/:id/approvals — list all approval decisions for a config request.
import { serviceClient } from '../../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const id = getRouterParam(event, 'id')!;
  const sb = serviceClient();
  const { data, error } = await sb
    .from('config_approvals')
    .select('*')
    .eq('request_id', id)
    .order('decided_at', { ascending: false });
  if (error) throw createError({ statusCode: 500, message: error.message });
  return { items: data ?? [], total: (data ?? []).length };
});

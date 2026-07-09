// GET /api/config/requests?status=pending|approved|rejected
// GET /api/config/requests?requester=<email>
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const q = getQuery(event);
  const sb = serviceClient();

  let query = sb.from('config_requests').select('*').order('created_at', { ascending: false }).limit(200);
  if (q.requester) {
    query = query.eq('requester', String(q.requester));
  } else if (q.status) {
    query = query.eq('status', String(q.status));
  } else {
    query = query.eq('status', 'pending');
  }

  const { data, error } = await query;
  if (error) throw createError({ statusCode: 500, message: error.message });
  return { items: data ?? [], total: (data ?? []).length };
});

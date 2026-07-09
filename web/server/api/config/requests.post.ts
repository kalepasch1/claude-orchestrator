// POST /api/config/requests — propose a fleet_config key/value change for approval.
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const body = await readBody<{ key?: string; value?: string; requester?: string }>(event);
  const key = String(body?.key ?? '').trim();
  const value = String(body?.value ?? '').trim();
  const requester = String(body?.requester ?? '').trim();
  if (!key || !value || !requester) {
    throw createError({ statusCode: 400, message: 'key, value, and requester are required' });
  }

  const sb = serviceClient();
  const { data, error } = await sb
    .from('config_requests')
    .insert({ key, value, requester, status: 'pending' })
    .select('*')
    .single();
  if (error) throw createError({ statusCode: 500, message: error.message });
  return { ok: true, request: data };
});

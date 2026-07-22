// POST /api/config/:id/approve — approve a pending config change request.
import { serviceClient } from '../../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const id = getRouterParam(event, 'id')!;
  const body = await readBody<{ approver?: string; reason?: string }>(event);
  const approver = String(body?.approver ?? '').trim();
  const reason = String(body?.reason ?? '').trim();
  if (!approver) throw createError({ statusCode: 400, message: 'approver is required' });

  const sb = serviceClient();
  const { data: req, error: readErr } = await sb
    .from('config_requests')
    .select('id, status')
    .eq('id', id)
    .maybeSingle();
  if (readErr) throw createError({ statusCode: 500, message: readErr.message });
  if (!req) throw createError({ statusCode: 404, message: 'config request not found' });
  if (req.status !== 'pending') {
    throw createError({ statusCode: 409, message: `request is already ${req.status}` });
  }

  const now = new Date().toISOString();
  const [{ error: updErr }, { data: approval, error: insErr }] = await Promise.all([
    sb.from('config_requests').update({ status: 'approved' }).eq('id', id),
    sb.from('config_approvals').insert({ request_id: id, approver, decision: 'approved', reason, decided_at: now }).select('*').single(),
  ]);
  if (updErr) throw createError({ statusCode: 500, message: updErr.message });
  if (insErr) throw createError({ statusCode: 500, message: insErr.message });
  return { ok: true, approval };
});

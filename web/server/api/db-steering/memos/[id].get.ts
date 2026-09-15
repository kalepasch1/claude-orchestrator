import { serviceClient } from '../../../utils/fleetSupabase'
import { requireConnectorUser } from '../../../utils/connectorFabric'

/**
 * One internal legal-memo draft with its body and evidence ledger. Internal work product
 * by construction: drafts are built from database findings for the fleet's own review and
 * are not legal advice — the response header says so for anything that proxies it.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export default defineEventHandler(async (event) => {
  await requireConnectorUser(event); const id = String(getRouterParam(event, 'id') || '')
  if (!UUID.test(id)) throw createError({ statusCode: 422, message: 'valid_memo_id_required' })
  setResponseHeader(event, 'X-Internal-Work-Product', 'not-legal-advice')
  const sb = serviceClient()
  const { data: memo, error } = await sb.from('legal_memo_drafts').select('*').eq('id', id).maybeSingle()
  if (error) throw createError({ statusCode: 500, message: error.message })
  if (!memo) throw createError({ statusCode: 404, message: 'memo_not_found' })
  // Second query: evidence rows with the finding embedded through legal_memo_evidence.finding_id → db_findings.id.
  const { data: evidence, error: evidenceError } = await sb.from('legal_memo_evidence').select('id,finding_id,argument_key,direction,weight,note,created_at,finding:db_findings!finding_id(id,title,severity,status,category,object_schema,object_name)').eq('memo_id', id).order('argument_key', { ascending: true })
  if (evidenceError) throw createError({ statusCode: 500, message: evidenceError.message })
  return { ok: true, memo, evidence: evidence || [] }
})

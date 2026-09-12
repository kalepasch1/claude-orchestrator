import { serviceClient } from '../../utils/fleetSupabase'
import { requireConnectorUser } from '../../utils/connectorFabric'
import { maskSource, severityRank } from '../../utils/dbSteering'

/**
 * Database Steering read model: sources (credential_ref masked to its kind), latest
 * posture per source, open findings, per-project briefs and memo drafts (no body —
 * fetch one through /api/db-steering/memos/[id]).
 * Filters: ?project=&days= (default 7; bounds the finding window by last_seen_at).
 */
export default defineEventHandler(async (event) => {
  await requireConnectorUser(event)
  const q = getQuery(event); const project = q.project ? String(q.project) : ''
  const days = Math.min(Math.max(Number(q.days) || 7, 1), 365); const since = new Date(Date.now() - days * 86400000).toISOString()
  const sb = serviceClient()
  const scoped = <T extends { eq: (column: string, value: string) => T }>(query: T): T => project ? query.eq('project', project) : query
  const [sourcesRes, postureRes, findingsRes, briefsRes, memosRes] = await Promise.all([
    scoped(sb.from('db_sources').select('id,project,label,provider,dialect,ref,region,credential_ref,config,discovered_via,status,enabled,capabilities,last_scan_at,last_ok_at,last_error,consecutive_failures,created_at,updated_at').order('label', { ascending: true })),
    scoped(sb.from('db_posture_snapshots').select('id,source_id,project,taken_at,score,counts,probe_stats,summary').order('taken_at', { ascending: false }).limit(200)),
    scoped(sb.from('db_findings').select('id,source_id,project,probe_id,category,severity,title,detail,object_schema,object_name,evidence_kinds,direction,remediation,status,first_seen_at,last_seen_at,occurrences,task_slug').eq('status', 'open').gte('last_seen_at', since).order('last_seen_at', { ascending: false }).limit(1000)),
    scoped(sb.from('db_steering_briefs').select('project,brief,findings_hash,open_counts,updated_at').order('updated_at', { ascending: false })),
    scoped(sb.from('legal_memo_drafts').select('id,project,memo_kind,title,thesis,arguments,evidence_hash,evidence_count,status,publication_state,gauntlet_at,model_provider,model_name,last_evidence_at,drafted_at,updated_at').order('updated_at', { ascending: false })),
  ])
  for (const res of [sourcesRes, postureRes, findingsRes, briefsRes, memosRes]) if (res.error) throw createError({ statusCode: 500, message: res.error.message })
  const posture: Record<string, any> = {}
  for (const snap of postureRes.data || []) if (!posture[snap.source_id]) posture[snap.source_id] = snap
  const open_by_severity: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0, info: 0 }
  for (const f of findingsRes.data || []) open_by_severity[f.severity] = (open_by_severity[f.severity] || 0) + 1
  const top = [...(findingsRes.data || [])].sort((a, b) => severityRank(b.severity) - severityRank(a.severity) || String(b.last_seen_at).localeCompare(String(a.last_seen_at))).slice(0, 50)
  return { ok: true, days, project: project || null, sources: (sourcesRes.data || []).map(maskSource), posture, findings: { open_by_severity, total_open: (findingsRes.data || []).length, top }, briefs: briefsRes.data || [], memos: memosRes.data || [] }
})

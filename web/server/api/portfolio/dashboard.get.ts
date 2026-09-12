// GET /api/portfolio/dashboard?tenantId=&mode= — the multi-entity portfolio view.
//
// One endpoint, two consumers: the private madeus.cc cockpit and the version
// embedded in Apparently. `mode` decides which affordances come back; the entity
// data is identical, because two implementations of this screen would drift and
// the embedded one is the one customers see.
//
// All ranking and shaping happens in server/utils/portfolioDashboard.ts, which
// is pure and tested against fixtures. This handler only gathers facts, and
// every gather is individually fail-soft: one missing table must not blank the
// whole screen.
import { serviceClient } from '../../utils/fleetSupabase'
import { buildDashboard, type DashboardMode, type EntityFacts } from '../../utils/portfolioDashboard'

async function safe<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await fn()
  } catch {
    return fallback
  }
}

export default defineEventHandler(async event => {
  const q = getQuery(event)
  const tenantId = String(q.tenantId || 'founding')
  const mode: DashboardMode = q.mode === 'apparently_embedded' ? 'apparently_embedded' : 'private_cockpit'

  const sb = serviceClient()

  // Entities. A tenant with none still gets an empty, well-formed screen rather
  // than an error page.
  let entityRows = await safe(async () => {
    const { data } = await sb.from('madeus_entities')
      .select('entity_id, display_name').eq('tenant_id', tenantId)
    return (data || []) as any[]
  }, [] as any[])

  if (!entityRows.length) entityRows = [{ entity_id: tenantId, display_name: 'All work' }]

  const facts: EntityFacts[] = await Promise.all(entityRows.map(async (row: any) => {
    const entityId = String(row.entity_id)

    const running = await safe(async () => (await sb.from('tasks')
      .select('id', { count: 'exact', head: true })
      .eq('tenant_id', tenantId).eq('state', 'RUNNING')).count ?? 0, 0)
    const queued = await safe(async () => (await sb.from('tasks')
      .select('id', { count: 'exact', head: true })
      .eq('tenant_id', tenantId).eq('state', 'QUEUED')).count ?? 0, 0)
    const approvals = await safe(async () => (await sb.from('approvals')
      .select('id, summary, created_at, risk_estimate_usd, kind')
      .eq('tenant_id', tenantId).eq('state', 'pending').limit(50)).data || [], [] as any[])
    const waves = await safe(async () => (await sb.from('waves')
      .select('id, label, eta').eq('tenant_id', tenantId)
      .order('eta', { ascending: true }).limit(1)).data || [], [] as any[])
    const releases = await safe(async () => (await sb.from('releases')
      .select('label, created_at').eq('tenant_id', tenantId)
      .order('created_at', { ascending: false }).limit(1)).data || [], [] as any[])

    const nextWave = waves[0]
    const latest = releases[0]

    return {
      entityId,
      displayName: String(row.display_name || entityId),
      runningTasks: running,
      queuedTasks: queued,
      pendingApprovals: approvals.map((a: any) => ({
        approvalId: String(a.id),
        entityId,
        summary: String(a.summary || ''),
        waitingSince: a.created_at ? Date.parse(a.created_at) : Date.now(),
        estimateUsd: a.risk_estimate_usd != null ? Number(a.risk_estimate_usd) : undefined,
        // A legal gate blocks the release card; other kinds are advisory.
        blocking: a.kind === 'legal_gate',
      })),
      nextWave: nextWave
        ? { waveId: String(nextWave.id), label: String(nextWave.label || ''), etaMs: nextWave.eta ? Date.parse(nextWave.eta) : null }
        : undefined,
      latestShipped: latest
        ? { label: String(latest.label || ''), at: latest.created_at ? Date.parse(latest.created_at) : 0 }
        : undefined,
    } as EntityFacts
  }))

  return { ok: true, tenantId, ...buildDashboard(mode, facts) }
})

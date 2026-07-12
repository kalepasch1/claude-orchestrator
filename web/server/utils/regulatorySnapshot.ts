/**
 * Regulatory Snapshot Generator — on-demand compliance report.
 * Pulls current state of all trust_safety events, legal holds, KYC statuses,
 * and audit logs across the fleet into a structured report.
 */
import { getAppClient, getAppConfig, type AppId } from '~/server/utils/appClients'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SnapshotItem {
  type: string  // 'legal_hold' | 'kyc_pending' | 'flagged_user' | 'compliance_alert' | 'audit_gap'
  severity: 'info' | 'warning' | 'critical'
  description: string
  details: any
  timestamp: string
}

export interface SnapshotSection {
  title: string
  app: string
  status: 'clean' | 'issues_found' | 'data_unavailable'
  items: SnapshotItem[]
  summary: string
}

export interface RegulatorySnapshot {
  id: string
  generatedAt: string
  generatedBy: string
  period: { from: string; to: string }
  sections: SnapshotSection[]
  summary: {
    totalApps: number
    appsWithIssues: number
    criticalItems: number
    warningItems: number
    overallStatus: 'compliant' | 'issues_detected' | 'action_required'
  }
}

// ---------------------------------------------------------------------------
// Per-app compliance query definitions
// ---------------------------------------------------------------------------

interface ComplianceFilter {
  column: string
  op: 'eq' | 'neq' | 'gt' | 'lt' | 'gte' | 'lte'
  value: any
}

interface ComplianceQuery {
  table: string
  filters: ComplianceFilter[]
  type: string
}

const COMPLIANCE_QUERIES: Record<string, ComplianceQuery[]> = {
  apparently: [
    { table: 'admin_board', filters: [{ column: 'status', op: 'neq', value: 'resolved' }], type: 'compliance_alert' },
    { table: 'legal_holds', filters: [{ column: 'active', op: 'eq', value: true }], type: 'legal_hold' },
    { table: 'submission_reviews', filters: [{ column: 'status', op: 'eq', value: 'pending' }], type: 'kyc_pending' },
  ],
  tomorrow: [
    { table: 'disputes', filters: [{ column: 'status', op: 'neq', value: 'resolved' }], type: 'compliance_alert' },
    { table: 'users', filters: [{ column: 'status', op: 'eq', value: 'suspended' }], type: 'flagged_user' },
  ],
  galop: [
    { table: 'compliance_flags', filters: [{ column: 'resolved', op: 'eq', value: false }], type: 'compliance_alert' },
    { table: 'player_bans', filters: [{ column: 'active', op: 'eq', value: true }], type: 'flagged_user' },
  ],
  smarter: [
    { table: 'governance_events', filters: [{ column: 'type', op: 'eq', value: 'kill_switch' }], type: 'compliance_alert' },
  ],
  hisanta: [
    { table: 'flagged_interactions', filters: [{ column: 'resolved', op: 'eq', value: false }], type: 'compliance_alert' },
  ],
  pareto: [
    { table: 'agency_grants', filters: [{ column: 'revoked', op: 'eq', value: false }], type: 'compliance_alert' },
  ],
}

// ---------------------------------------------------------------------------
// Severity classification
// ---------------------------------------------------------------------------

function classifySeverity(type: string, _row: any): 'info' | 'warning' | 'critical' {
  if (type === 'legal_hold') return 'critical'
  if (type === 'flagged_user') return 'warning'
  if (type === 'kyc_pending') return 'warning'
  if (type === 'compliance_alert') return 'warning'
  if (type === 'audit_gap') return 'info'
  return 'info'
}

function describeItem(type: string, row: any, table: string): string {
  const id = row.id || row.uuid || 'unknown'
  switch (type) {
    case 'legal_hold':
      return `Active legal hold #${id}: ${row.reason || row.description || 'no description'}`
    case 'kyc_pending':
      return `Pending KYC review #${id}: ${row.status || 'pending'}`
    case 'flagged_user':
      return `Flagged/suspended user #${id}: ${row.reason || row.email || row.username || 'no details'}`
    case 'compliance_alert':
      return `Compliance alert from ${table} #${id}: ${row.type || row.status || row.description || 'open issue'}`
    default:
      return `${type} in ${table} #${id}`
  }
}

// ---------------------------------------------------------------------------
// In-memory snapshot store (production would use DB)
// ---------------------------------------------------------------------------

const snapshotStore = new Map<string, RegulatorySnapshot>()

function generateId(): string {
  return `snap-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

// ---------------------------------------------------------------------------
// Core functions
// ---------------------------------------------------------------------------

async function queryAppCompliance(appId: string, queries: ComplianceQuery[], period: { from: string; to: string }): Promise<SnapshotSection> {
  const client = getAppClient(appId as AppId)
  const config = getAppConfig(appId as AppId)
  const items: SnapshotItem[] = []

  if (!client) {
    return {
      title: config.name,
      app: appId,
      status: 'data_unavailable',
      items: [],
      summary: `${config.name}: Supabase client not configured — skipped.`,
    }
  }

  for (const q of queries) {
    try {
      let query = client.from(q.table).select('*').limit(100)

      // Apply filters
      for (const f of q.filters) {
        switch (f.op) {
          case 'eq': query = query.eq(f.column, f.value); break
          case 'neq': query = query.neq(f.column, f.value); break
          case 'gt': query = query.gt(f.column, f.value); break
          case 'lt': query = query.lt(f.column, f.value); break
          case 'gte': query = query.gte(f.column, f.value); break
          case 'lte': query = query.lte(f.column, f.value); break
        }
      }

      // Try to filter by period if the table has a created_at column
      query = query.gte('created_at', period.from).lte('created_at', period.to)

      const { data, error } = await query

      if (error) {
        // Table might not exist or created_at might not exist — retry without date filter
        let retryQuery = client.from(q.table).select('*').limit(100)
        for (const f of q.filters) {
          switch (f.op) {
            case 'eq': retryQuery = retryQuery.eq(f.column, f.value); break
            case 'neq': retryQuery = retryQuery.neq(f.column, f.value); break
            case 'gt': retryQuery = retryQuery.gt(f.column, f.value); break
            case 'lt': retryQuery = retryQuery.lt(f.column, f.value); break
            case 'gte': retryQuery = retryQuery.gte(f.column, f.value); break
            case 'lte': retryQuery = retryQuery.lte(f.column, f.value); break
          }
        }
        const retry = await retryQuery
        if (retry.error) {
          // Table truly doesn't exist or another error — skip silently
          continue
        }
        if (retry.data) {
          for (const row of retry.data) {
            items.push({
              type: q.type,
              severity: classifySeverity(q.type, row),
              description: describeItem(q.type, row, q.table),
              details: row,
              timestamp: row.created_at || row.updated_at || new Date().toISOString(),
            })
          }
        }
        continue
      }

      if (data) {
        for (const row of data) {
          items.push({
            type: q.type,
            severity: classifySeverity(q.type, row),
            description: describeItem(q.type, row, q.table),
            details: row,
            timestamp: row.created_at || row.updated_at || new Date().toISOString(),
          })
        }
      }
    } catch {
      // Fail-soft: skip this query
    }
  }

  const criticals = items.filter(i => i.severity === 'critical').length
  const warnings = items.filter(i => i.severity === 'warning').length

  let status: SnapshotSection['status'] = 'clean'
  if (items.length > 0) status = 'issues_found'

  let summary = `${config.name}: ${items.length} item(s) found`
  if (criticals > 0) summary += ` — ${criticals} critical`
  if (warnings > 0) summary += `, ${warnings} warning(s)`
  if (items.length === 0) summary = `${config.name}: No compliance issues detected.`

  return { title: config.name, app: appId, status, items, summary }
}

export function classifyOverallStatus(sections: SnapshotSection[]): 'compliant' | 'issues_detected' | 'action_required' {
  const allItems = sections.flatMap(s => s.items)
  const criticals = allItems.filter(i => i.severity === 'critical').length
  if (criticals > 0) return 'action_required'
  const warnings = allItems.filter(i => i.severity === 'warning').length
  if (warnings > 0) return 'issues_detected'
  return 'compliant'
}

export async function generateSnapshot(period?: { from?: string; to?: string }): Promise<RegulatorySnapshot> {
  const now = new Date()
  const defaultFrom = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString()
  const resolvedPeriod = {
    from: period?.from || defaultFrom,
    to: period?.to || now.toISOString(),
  }

  const sections: SnapshotSection[] = []

  // Query each app in parallel
  const appIds = Object.keys(COMPLIANCE_QUERIES) as string[]
  const results = await Promise.allSettled(
    appIds.map(appId => queryAppCompliance(appId, COMPLIANCE_QUERIES[appId], resolvedPeriod))
  )

  for (const result of results) {
    if (result.status === 'fulfilled') {
      sections.push(result.value)
    }
  }

  const allItems = sections.flatMap(s => s.items)

  const snapshot: RegulatorySnapshot = {
    id: generateId(),
    generatedAt: now.toISOString(),
    generatedBy: 'orchestrator',
    period: resolvedPeriod,
    sections,
    summary: {
      totalApps: sections.length,
      appsWithIssues: sections.filter(s => s.status === 'issues_found').length,
      criticalItems: allItems.filter(i => i.severity === 'critical').length,
      warningItems: allItems.filter(i => i.severity === 'warning').length,
      overallStatus: classifyOverallStatus(sections),
    },
  }

  snapshotStore.set(snapshot.id, snapshot)
  return snapshot
}

export async function getRecentSnapshots(): Promise<Pick<RegulatorySnapshot, 'id' | 'generatedAt' | 'summary' | 'period'>[]> {
  return [...snapshotStore.values()]
    .sort((a, b) => b.generatedAt.localeCompare(a.generatedAt))
    .slice(0, 50)
    .map(s => ({
      id: s.id,
      generatedAt: s.generatedAt,
      period: s.period,
      summary: s.summary,
    }))
}

export function getSnapshotById(id: string): RegulatorySnapshot | null {
  return snapshotStore.get(id) ?? null
}

export function exportSnapshotHTML(snapshot: RegulatorySnapshot): string {
  const statusColors: Record<string, string> = {
    compliant: '#22c55e',
    issues_detected: '#eab308',
    action_required: '#ef4444',
  }
  const statusLabels: Record<string, string> = {
    compliant: 'COMPLIANT',
    issues_detected: 'ISSUES DETECTED',
    action_required: 'ACTION REQUIRED',
  }
  const severityColors: Record<string, string> = {
    info: '#6b7280',
    warning: '#eab308',
    critical: '#ef4444',
  }
  const sectionStatusColors: Record<string, string> = {
    clean: '#22c55e',
    issues_found: '#eab308',
    data_unavailable: '#6b7280',
  }

  const sectionsHTML = snapshot.sections.map(s => `
    <div style="margin-bottom:24px;border:1px solid #374151;border-radius:8px;overflow:hidden;">
      <div style="background:#1f2937;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;">
        <h3 style="margin:0;font-size:16px;color:#e5e7eb;">${s.title}</h3>
        <span style="font-size:12px;font-weight:600;color:${sectionStatusColors[s.status] || '#6b7280'};">${s.status.replace('_', ' ').toUpperCase()}</span>
      </div>
      <div style="padding:16px;">
        ${s.items.length === 0
          ? '<p style="color:#6b7280;font-size:14px;margin:0;">No issues found.</p>'
          : `<table style="width:100%;border-collapse:collapse;font-size:13px;">
              <thead><tr style="border-bottom:1px solid #374151;">
                <th style="text-align:left;padding:6px 8px;color:#9ca3af;">Severity</th>
                <th style="text-align:left;padding:6px 8px;color:#9ca3af;">Type</th>
                <th style="text-align:left;padding:6px 8px;color:#9ca3af;">Description</th>
                <th style="text-align:left;padding:6px 8px;color:#9ca3af;">Timestamp</th>
              </tr></thead>
              <tbody>${s.items.map(item => `
                <tr style="border-bottom:1px solid #1f2937;">
                  <td style="padding:6px 8px;"><span style="color:${severityColors[item.severity]};font-weight:600;text-transform:uppercase;font-size:11px;">${item.severity}</span></td>
                  <td style="padding:6px 8px;color:#d1d5db;">${item.type}</td>
                  <td style="padding:6px 8px;color:#d1d5db;">${item.description}</td>
                  <td style="padding:6px 8px;color:#9ca3af;font-size:12px;">${new Date(item.timestamp).toLocaleString()}</td>
                </tr>`).join('')}
              </tbody>
            </table>`
        }
        <p style="margin:12px 0 0;font-size:13px;color:#9ca3af;">${s.summary}</p>
      </div>
    </div>`).join('')

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Regulatory Compliance Snapshot — ${new Date(snapshot.generatedAt).toLocaleDateString()}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #111827; color: #e5e7eb; margin: 0; padding: 40px; }
    @media print { body { background: white; color: #111827; } }
  </style>
</head>
<body>
  <div style="max-width:900px;margin:0 auto;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:32px;">
      <div>
        <h1 style="margin:0 0 4px;font-size:24px;color:#e5e7eb;">Regulatory Compliance Snapshot</h1>
        <p style="margin:0;font-size:14px;color:#9ca3af;">Generated: ${new Date(snapshot.generatedAt).toLocaleString()}</p>
        <p style="margin:4px 0 0;font-size:13px;color:#6b7280;">Period: ${new Date(snapshot.period.from).toLocaleDateString()} — ${new Date(snapshot.period.to).toLocaleDateString()}</p>
      </div>
      <div style="text-align:right;">
        <div style="font-size:14px;font-weight:700;color:${statusColors[snapshot.summary.overallStatus]};border:2px solid ${statusColors[snapshot.summary.overallStatus]};padding:8px 16px;border-radius:8px;">
          ${statusLabels[snapshot.summary.overallStatus]}
        </div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:16px;margin-bottom:32px;">
      <div style="background:#1f2937;border-radius:8px;padding:16px;text-align:center;">
        <div style="font-size:24px;font-weight:700;color:#e5e7eb;">${snapshot.summary.totalApps}</div>
        <div style="font-size:12px;color:#9ca3af;margin-top:4px;">Apps Scanned</div>
      </div>
      <div style="background:#1f2937;border-radius:8px;padding:16px;text-align:center;">
        <div style="font-size:24px;font-weight:700;color:#eab308;">${snapshot.summary.appsWithIssues}</div>
        <div style="font-size:12px;color:#9ca3af;margin-top:4px;">Apps with Issues</div>
      </div>
      <div style="background:#1f2937;border-radius:8px;padding:16px;text-align:center;">
        <div style="font-size:24px;font-weight:700;color:#ef4444;">${snapshot.summary.criticalItems}</div>
        <div style="font-size:12px;color:#9ca3af;margin-top:4px;">Critical Items</div>
      </div>
      <div style="background:#1f2937;border-radius:8px;padding:16px;text-align:center;">
        <div style="font-size:24px;font-weight:700;color:#eab308;">${snapshot.summary.warningItems}</div>
        <div style="font-size:12px;color:#9ca3af;margin-top:4px;">Warning Items</div>
      </div>
    </div>

    ${sectionsHTML}

    <div style="margin-top:32px;padding-top:16px;border-top:1px solid #374151;font-size:11px;color:#6b7280;text-align:center;">
      SMRTER OPS — Regulatory Snapshot ID: ${snapshot.id} — Confidential
    </div>
  </div>
</body>
</html>`
}

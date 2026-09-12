// Pure aggregation behind GET /api/config/summary.
//
// Kept out of the event handler so it is testable the way the rest of server/utils is:
// the endpoint does Supabase I/O, this does the arithmetic. No imports, no clock — `now`
// is passed in so age/staleness assertions are deterministic under test.

export interface ConfigRequestRow {
  id: string
  key?: string | null
  value?: string | null
  requester?: string | null
  status?: string | null
  created_at?: string | null
}

export interface ConfigApprovalRow {
  request_id?: string | null
  approver?: string | null
  decision?: string | null
  reason?: string | null
  decided_at?: string | null
}

// A pending request older than this has been waiting on a human long enough to be worth
// surfacing as its own number rather than sitting silently at the bottom of the list.
export const STALE_PENDING_MS = 24 * 60 * 60 * 1000

function parseTime(value: string | null | undefined): number | null {
  if (!value) return null
  const t = Date.parse(value)
  return Number.isFinite(t) ? t : null
}

export function summarizeConfigChanges(
  requests: ConfigRequestRow[],
  approvals: ConfigApprovalRow[],
  now: number,
  errors: string[] = [],
) {
  const counts = { pending: 0, approved: 0, rejected: 0, other: 0 }
  for (const r of requests) {
    const s = String(r.status ?? '')
    if (s === 'pending') counts.pending++
    else if (s === 'approved') counts.approved++
    else if (s === 'rejected') counts.rejected++
    else counts.other++
  }

  const pendingRows = requests.filter((r) => r.status === 'pending')

  // An unparseable created_at must not silently read as "waiting forever" and page someone,
  // so rows without a usable timestamp are aged 0 and never counted stale.
  const pending = pendingRows.map((r) => {
    const created = parseTime(r.created_at)
    return {
      id: r.id,
      key: r.key ?? null,
      value: r.value ?? null,
      requester: r.requester ?? null,
      created_at: r.created_at ?? null,
      ageMs: created === null ? 0 : Math.max(0, now - created),
    }
  })

  const stale = pending.filter((r) => r.ageMs > STALE_PENDING_MS)

  // Approvals arrive newest-first; the first one seen per request is the current decision,
  // which gives the dashboard a "who last touched this key" column with no extra round trip.
  const decisionByRequest = new Map<string, ConfigApprovalRow>()
  for (const a of approvals) {
    const rid = String(a.request_id ?? '')
    if (rid && !decisionByRequest.has(rid)) decisionByRequest.set(rid, a)
  }

  const recent = requests.slice(0, 25).map((r) => ({
    id: r.id,
    key: r.key ?? null,
    status: r.status ?? null,
    requester: r.requester ?? null,
    created_at: r.created_at ?? null,
    lastDecision: decisionByRequest.get(String(r.id)) ?? null,
  }))

  return {
    generatedAt: new Date(now).toISOString(),
    counts,
    total: requests.length,
    stalePending: stale.length,
    stalePendingIds: stale.map((r) => r.id),
    pending,
    recent,
    decisions: approvals.slice(0, 25),
    errors,
  }
}

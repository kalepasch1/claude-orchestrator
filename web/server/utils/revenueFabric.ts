/**
 * Revenue Fabric — aggregates billing data from all apps into a unified P&L.
 * Queries each app's billing/transaction tables via the proxy layer (getAppClient).
 */
import { getAppClient, getAppConfig, ALL_APP_IDS, type AppId } from './appClients'

export interface AppRevenue {
  app: string
  appName: string
  period: string // YYYY-MM
  mrr: number
  transactions: number
  refunds: number
  netRevenue: number
  currency: string
  note?: string
}

export interface PortfolioSummary {
  totalMRR: number
  totalTransactions: number
  totalRefunds: number
  totalNetRevenue: number
  byApp: AppRevenue[]
  trend: { period: string; revenue: number }[]
  gaps: string[]
}

// Map each app to its billing table(s)
const BILLING_TABLES: Record<string, { table: string; amountCol: string; dateCol: string; statusCol?: string; refundStatus?: string }> = {
  apparently: { table: 'billing_events', amountCol: 'amount', dateCol: 'created_at' },
  tomorrow: { table: 'transactions', amountCol: 'notional_value', dateCol: 'created_at', statusCol: 'status', refundStatus: 'refunded' },
  smarter: { table: 'billing_events', amountCol: 'amount', dateCol: 'created_at' },
  galop: { table: 'transactions', amountCol: 'amount', dateCol: 'created_at' },
  hisanta: { table: 'purchases', amountCol: 'amount', dateCol: 'created_at' },
  pareto: { table: 'transactions', amountCol: 'amount', dateCol: 'created_at' },
}

function monthsAgoISO(months: number): string {
  const d = new Date()
  d.setMonth(d.getMonth() - months)
  d.setDate(1)
  d.setHours(0, 0, 0, 0)
  return d.toISOString()
}

function toYYYYMM(dateStr: string): string {
  return dateStr.slice(0, 7)
}

/**
 * Fetch revenue data for a single app, grouped by month.
 * Returns empty array with a note if the app isn't configured or the table doesn't exist.
 */
export async function fetchAppRevenue(appId: AppId, months = 6): Promise<{ revenues: AppRevenue[]; gap?: string }> {
  const config = getAppConfig(appId)
  const billing = BILLING_TABLES[appId]

  if (!billing) {
    return { revenues: [], gap: `${appId}: no billing table configured` }
  }

  const client = getAppClient(appId)
  if (!client) {
    return { revenues: [], gap: `${appId}: not connected (missing env vars)` }
  }

  const since = monthsAgoISO(months)

  try {
    const { data, error } = await client
      .from(billing.table)
      .select(`${billing.amountCol}, ${billing.dateCol}${billing.statusCol ? ', ' + billing.statusCol : ''}`)
      .gte(billing.dateCol, since)
      .order(billing.dateCol, { ascending: true })
      .limit(10000)

    if (error) {
      // Table probably doesn't exist
      return { revenues: [], gap: `${appId}: query failed — ${error.message}` }
    }

    if (!data || data.length === 0) {
      return { revenues: [], gap: `${appId}: no billing data in period` }
    }

    // Group by month
    const byMonth = new Map<string, { total: number; count: number; refunds: number }>()

    for (const row of data) {
      const period = toYYYYMM(row[billing.dateCol])
      const amount = Number(row[billing.amountCol]) || 0
      const isRefund = billing.statusCol && billing.refundStatus
        ? row[billing.statusCol] === billing.refundStatus
        : amount < 0

      if (!byMonth.has(period)) {
        byMonth.set(period, { total: 0, count: 0, refunds: 0 })
      }
      const bucket = byMonth.get(period)!
      if (isRefund) {
        bucket.refunds += Math.abs(amount)
      } else {
        bucket.total += amount
      }
      bucket.count++
    }

    const revenues: AppRevenue[] = []
    for (const [period, bucket] of byMonth) {
      revenues.push({
        app: appId,
        appName: config.name,
        period,
        mrr: bucket.total, // approximate MRR = total for the month
        transactions: bucket.count,
        refunds: bucket.refunds,
        netRevenue: bucket.total - bucket.refunds,
        currency: 'USD',
      })
    }

    return { revenues }
  } catch (err: any) {
    return { revenues: [], gap: `${appId}: ${err?.message ?? 'unknown error'}` }
  }
}

/**
 * Aggregate revenue across all apps into a portfolio summary.
 */
export async function getPortfolioSummary(months = 6): Promise<PortfolioSummary> {
  const gaps: string[] = []
  const allRevenues: AppRevenue[] = []

  // Query all apps in parallel
  const results = await Promise.allSettled(
    ALL_APP_IDS
      .filter((id) => id !== 'orchestrator') // orchestrator has no billing
      .map((id) => fetchAppRevenue(id, months))
  )

  for (const result of results) {
    if (result.status === 'fulfilled') {
      allRevenues.push(...result.value.revenues)
      if (result.value.gap) gaps.push(result.value.gap)
    } else {
      gaps.push(`fetch error: ${result.reason}`)
    }
  }

  // Compute totals — use latest month for MRR
  const sortedPeriods = [...new Set(allRevenues.map((r) => r.period))].sort()
  const latestPeriod = sortedPeriods[sortedPeriods.length - 1] ?? ''
  const latestMonth = allRevenues.filter((r) => r.period === latestPeriod)

  const totalMRR = latestMonth.reduce((s, r) => s + r.mrr, 0)
  const totalTransactions = allRevenues.reduce((s, r) => s + r.transactions, 0)
  const totalRefunds = allRevenues.reduce((s, r) => s + r.refunds, 0)
  const totalNetRevenue = allRevenues.reduce((s, r) => s + r.netRevenue, 0)

  // Build trend (aggregate by period across all apps)
  const trendMap = new Map<string, number>()
  for (const r of allRevenues) {
    trendMap.set(r.period, (trendMap.get(r.period) ?? 0) + r.netRevenue)
  }
  const trend = [...trendMap.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([period, revenue]) => ({ period, revenue }))

  return {
    totalMRR,
    totalTransactions,
    totalRefunds,
    totalNetRevenue,
    byApp: allRevenues,
    trend,
    gaps,
  }
}

/**
 * Revenue timeline for charting — monthly totals across all apps.
 */
export async function getRevenueTimeline(months = 12): Promise<{ period: string; revenue: number; byApp: Record<string, number> }[]> {
  const summary = await getPortfolioSummary(months)

  // Build per-period, per-app breakdown
  const periodMap = new Map<string, Record<string, number>>()
  for (const r of summary.byApp) {
    if (!periodMap.has(r.period)) periodMap.set(r.period, {})
    const bucket = periodMap.get(r.period)!
    bucket[r.app] = (bucket[r.app] ?? 0) + r.netRevenue
  }

  return summary.trend.map((t) => ({
    period: t.period,
    revenue: t.revenue,
    byApp: periodMap.get(t.period) ?? {},
  }))
}

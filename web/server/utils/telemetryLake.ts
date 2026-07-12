/**
 * Fleet Telemetry Lake — time-series storage for all fleet events.
 * Stores events in a Supabase `fleet_telemetry` table with time-bucketed aggregation queries.
 * Enables "show me error rates over the last quarter" in NL Admin.
 *
 * Table schema (create via migration):
 *   id          uuid primary key default gen_random_uuid()
 *   timestamp   timestamptz not null
 *   app         text not null
 *   domain      text not null default ''
 *   metric      text not null
 *   value       double precision not null default 0
 *   tags        jsonb default '{}'
 *   created_at  timestamptz default now()
 *
 * Index: (timestamp, app, metric)
 */
import { serviceClient } from './fleetSupabase'

export interface TelemetryPoint {
  timestamp: string
  app: string
  domain: string
  metric: string
  value: number
  tags?: Record<string, string>
}

export interface TimeSeriesQuery {
  apps?: string[]
  metrics?: string[]
  domains?: string[]
  from: string
  to: string
  bucket: '1h' | '1d' | '1w' | '1M'
}

export interface TimeSeriesBucket {
  timestamp: string
  values: Record<string, number>
}

export interface TimeSeriesResult {
  buckets: TimeSeriesBucket[]
  summary: { min: number; max: number; avg: number; total: number }
}

const BUCKET_SQL: Record<string, string> = {
  '1h': 'hour',
  '1d': 'day',
  '1w': 'week',
  '1M': 'month',
}

/**
 * Ingest a single fleet event as a telemetry point.
 * Called from the fleet ingest pipeline on every event.
 */
export async function ingestEvent(event: any): Promise<void> {
  const sb = serviceClient()
  const point: Partial<TelemetryPoint> = {
    timestamp: event.at || event.timestamp || new Date().toISOString(),
    app: event.product || event.app || 'unknown',
    domain: event.domain || '',
    metric: event.category || event.metric || 'event_count',
    value: event.value ?? 1,
    tags: event.tags || {},
  }
  await sb.from('fleet_telemetry').insert(point)
}

/**
 * Ingest a batch of telemetry points.
 */
export async function ingestBatch(points: TelemetryPoint[]): Promise<{ inserted: number }> {
  if (!points.length) return { inserted: 0 }
  const sb = serviceClient()
  const rows = points.map(p => ({
    timestamp: p.timestamp,
    app: p.app,
    domain: p.domain || '',
    metric: p.metric,
    value: p.value ?? 0,
    tags: p.tags || {},
  }))
  const { error, count } = await sb.from('fleet_telemetry').insert(rows)
  if (error) throw new Error(`Telemetry ingest failed: ${error.message}`)
  return { inserted: rows.length }
}

/**
 * Query telemetry with time-bucketed aggregation.
 */
export async function query(q: TimeSeriesQuery): Promise<TimeSeriesResult> {
  const sb = serviceClient()
  const bucketUnit = BUCKET_SQL[q.bucket] || 'day'

  // Build filter for the raw query
  let rpcQuery = sb
    .from('fleet_telemetry')
    .select('timestamp, app, metric, value')
    .gte('timestamp', q.from)
    .lte('timestamp', q.to)
    .order('timestamp', { ascending: true })

  if (q.apps?.length) rpcQuery = rpcQuery.in('app', q.apps)
  if (q.metrics?.length) rpcQuery = rpcQuery.in('metric', q.metrics)
  if (q.domains?.length) rpcQuery = rpcQuery.in('domain', q.domains)

  const { data, error } = await rpcQuery.limit(50000)
  if (error) throw new Error(`Telemetry query failed: ${error.message}`)

  const rows = data || []

  // Client-side bucketing (Supabase JS doesn't support date_trunc natively)
  const bucketMap = new Map<string, Record<string, number[]>>()

  for (const row of rows) {
    const ts = new Date(row.timestamp)
    const bucketKey = truncateDate(ts, bucketUnit)
    const metricKey = `${row.app}:${row.metric}`

    if (!bucketMap.has(bucketKey)) bucketMap.set(bucketKey, {})
    const bucket = bucketMap.get(bucketKey)!
    if (!bucket[metricKey]) bucket[metricKey] = []
    bucket[metricKey].push(row.value)
  }

  // Aggregate each bucket
  const buckets: TimeSeriesBucket[] = []
  const allValues: number[] = []

  for (const [ts, metrics] of Array.from(bucketMap.entries()).sort()) {
    const values: Record<string, number> = {}
    for (const [key, vals] of Object.entries(metrics)) {
      const sum = vals.reduce((a, b) => a + b, 0)
      values[key] = sum
      allValues.push(sum)
    }
    buckets.push({ timestamp: ts, values })
  }

  const summary = allValues.length > 0
    ? {
        min: Math.min(...allValues),
        max: Math.max(...allValues),
        avg: Math.round((allValues.reduce((a, b) => a + b, 0) / allValues.length) * 100) / 100,
        total: allValues.reduce((a, b) => a + b, 0),
      }
    : { min: 0, max: 0, avg: 0, total: 0 }

  return { buckets, summary }
}

/**
 * List all distinct metric names in the telemetry table.
 */
export async function getMetricNames(): Promise<string[]> {
  const sb = serviceClient()
  const { data } = await sb
    .from('fleet_telemetry')
    .select('metric')
    .limit(1000)

  if (!data) return []
  const unique = new Set(data.map((r: any) => r.metric))
  return Array.from(unique).sort()
}

/**
 * Get retention statistics about the telemetry lake.
 */
export async function getRetentionStats(): Promise<{
  totalPoints: number
  oldestPoint: string | null
  newestPoint: string | null
  sizeEstimate: string
}> {
  const sb = serviceClient()

  const [countRes, oldestRes, newestRes] = await Promise.all([
    sb.from('fleet_telemetry').select('id', { count: 'exact', head: true }),
    sb.from('fleet_telemetry').select('timestamp').order('timestamp', { ascending: true }).limit(1).maybeSingle(),
    sb.from('fleet_telemetry').select('timestamp').order('timestamp', { ascending: false }).limit(1).maybeSingle(),
  ])

  const totalPoints = countRes.count ?? 0
  // Rough estimate: ~200 bytes per row
  const sizeBytes = totalPoints * 200
  const sizeEstimate = sizeBytes < 1024 * 1024
    ? `${Math.round(sizeBytes / 1024)} KB`
    : `${Math.round(sizeBytes / (1024 * 1024))} MB`

  return {
    totalPoints,
    oldestPoint: oldestRes.data?.timestamp ?? null,
    newestPoint: newestRes.data?.timestamp ?? null,
    sizeEstimate,
  }
}

/**
 * Delete telemetry data older than N days.
 */
export async function pruneOlderThan(days: number): Promise<number> {
  const sb = serviceClient()
  const cutoff = new Date(Date.now() - days * 86400000).toISOString()
  const { count } = await sb
    .from('fleet_telemetry')
    .delete({ count: 'exact' })
    .lt('timestamp', cutoff)
  return count ?? 0
}

// ---- helpers ----

function truncateDate(d: Date, unit: string): string {
  const iso = d.toISOString()
  switch (unit) {
    case 'hour':
      return iso.slice(0, 13) + ':00:00.000Z'
    case 'day':
      return iso.slice(0, 10) + 'T00:00:00.000Z'
    case 'week': {
      const day = d.getUTCDay()
      const diff = d.getUTCDate() - day + (day === 0 ? -6 : 1) // Monday start
      const monday = new Date(d)
      monday.setUTCDate(diff)
      return monday.toISOString().slice(0, 10) + 'T00:00:00.000Z'
    }
    case 'month':
      return iso.slice(0, 7) + '-01T00:00:00.000Z'
    default:
      return iso.slice(0, 10) + 'T00:00:00.000Z'
  }
}

/**
 * Anomaly Radar -- polls fleet_events and proxy data for statistical outliers.
 * Uses Z-score detection: if a metric deviates >2.5 sigma from its 7-day rolling mean, flag it.
 */
import { getAppClient, ALL_APP_IDS, type AppId, getAppConfig } from './appClients'

export interface AnomalyAlert {
  id: string
  app: string
  metric: string
  current: number
  baseline: number
  stddev: number
  zscore: number
  severity: 'info' | 'warning' | 'critical'
  detected_at: string
  message: string
}

interface ZScoreResult {
  mean: number
  stddev: number
  zscore: number
}

// In-memory cache for alerts between scans
let cachedAlerts: AnomalyAlert[] = []
let lastScanTime: string | null = null

export function computeZScore(values: number[], current: number): ZScoreResult {
  if (values.length === 0) {
    return { mean: 0, stddev: 0, zscore: 0 }
  }

  const mean = values.reduce((sum, v) => sum + v, 0) / values.length
  const variance = values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / values.length
  const stddev = Math.sqrt(variance)

  // If stddev is 0 (all values identical), zscore is 0 unless current differs
  if (stddev === 0) {
    return { mean, stddev: 0, zscore: current === mean ? 0 : current > mean ? 4 : -4 }
  }

  const zscore = (current - mean) / stddev
  return { mean, stddev, zscore }
}

export function classifySeverity(zscore: number): 'info' | 'warning' | 'critical' {
  const abs = Math.abs(zscore)
  if (abs >= 3.5) return 'critical'
  if (abs >= 2.5) return 'warning'
  return 'info'
}

function makeId(app: string, metric: string): string {
  return `${app}:${metric}:${Date.now()}`
}

/**
 * Query fleet_events for a given app over the last 7 days, group by hour,
 * and detect anomalies in event volume, error rate, and rejection rate.
 */
export async function scanApp(appId: AppId): Promise<AnomalyAlert[]> {
  const client = getAppClient(appId)
  if (!client) return []

  const config = getAppConfig(appId)
  const appName = config.name
  const alerts: AnomalyAlert[] = []
  const now = new Date()
  const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)

  try {
    // Query fleet_events for this app
    const { data: events, error } = await client
      .from('fleet_events')
      .select('id, event_type, created_at, payload')
      .gte('created_at', sevenDaysAgo.toISOString())
      .order('created_at', { ascending: true })

    if (error || !events) return []

    // Group events by hour
    const hourlyBuckets = new Map<string, { total: number; errors: number; rejections: number }>()

    for (const evt of events) {
      const hourKey = evt.created_at?.slice(0, 13) // YYYY-MM-DDTHH
      if (!hourKey) continue

      if (!hourlyBuckets.has(hourKey)) {
        hourlyBuckets.set(hourKey, { total: 0, errors: 0, rejections: 0 })
      }
      const bucket = hourlyBuckets.get(hourKey)!
      bucket.total++

      const eventType = (evt.event_type || '').toLowerCase()
      const payloadStr = JSON.stringify(evt.payload || {}).toLowerCase()

      if (eventType.includes('error') || eventType.includes('fail') || payloadStr.includes('error')) {
        bucket.errors++
      }
      if (eventType.includes('reject') || eventType.includes('denied') || payloadStr.includes('rejected')) {
        bucket.rejections++
      }
    }

    if (hourlyBuckets.size < 2) return [] // Not enough data

    const sortedKeys = Array.from(hourlyBuckets.keys()).sort()
    const latestKey = sortedKeys[sortedKeys.length - 1]
    const historicalKeys = sortedKeys.slice(0, -1)

    if (historicalKeys.length === 0) return []

    const latest = hourlyBuckets.get(latestKey)!

    // 1. Event volume anomaly
    const historicalVolumes = historicalKeys.map(k => hourlyBuckets.get(k)!.total)
    const volumeResult = computeZScore(historicalVolumes, latest.total)
    if (Math.abs(volumeResult.zscore) >= 2.5) {
      const severity = classifySeverity(volumeResult.zscore)
      const direction = volumeResult.zscore > 0 ? 'spike' : 'drop'
      alerts.push({
        id: makeId(appId, 'event_volume'),
        app: appName,
        metric: 'Event Volume',
        current: latest.total,
        baseline: Math.round(volumeResult.mean * 100) / 100,
        stddev: Math.round(volumeResult.stddev * 100) / 100,
        zscore: Math.round(volumeResult.zscore * 100) / 100,
        severity,
        detected_at: now.toISOString(),
        message: `${appName}: event volume ${direction} -- ${latest.total} events/hr vs baseline ${Math.round(volumeResult.mean)}/hr (${Math.abs(Math.round(volumeResult.zscore * 10) / 10)} sigma)`,
      })
    }

    // 2. Error rate anomaly
    const historicalErrorRates = historicalKeys.map(k => {
      const b = hourlyBuckets.get(k)!
      return b.total > 0 ? b.errors / b.total : 0
    })
    const currentErrorRate = latest.total > 0 ? latest.errors / latest.total : 0
    const errorResult = computeZScore(historicalErrorRates, currentErrorRate)
    if (Math.abs(errorResult.zscore) >= 2.5) {
      const severity = classifySeverity(errorResult.zscore)
      alerts.push({
        id: makeId(appId, 'error_rate'),
        app: appName,
        metric: 'Error Rate',
        current: Math.round(currentErrorRate * 10000) / 100,
        baseline: Math.round(errorResult.mean * 10000) / 100,
        stddev: Math.round(errorResult.stddev * 10000) / 100,
        zscore: Math.round(errorResult.zscore * 100) / 100,
        severity,
        detected_at: now.toISOString(),
        message: `${appName}: error rate at ${Math.round(currentErrorRate * 100)}% vs baseline ${Math.round(errorResult.mean * 100)}% (${Math.abs(Math.round(errorResult.zscore * 10) / 10)} sigma)`,
      })
    }

    // 3. Rejection rate anomaly
    const historicalRejectionRates = historicalKeys.map(k => {
      const b = hourlyBuckets.get(k)!
      return b.total > 0 ? b.rejections / b.total : 0
    })
    const currentRejectionRate = latest.total > 0 ? latest.rejections / latest.total : 0
    const rejectionResult = computeZScore(historicalRejectionRates, currentRejectionRate)
    if (Math.abs(rejectionResult.zscore) >= 2.5) {
      const severity = classifySeverity(rejectionResult.zscore)
      alerts.push({
        id: makeId(appId, 'rejection_rate'),
        app: appName,
        metric: 'Rejection Rate',
        current: Math.round(currentRejectionRate * 10000) / 100,
        baseline: Math.round(rejectionResult.mean * 10000) / 100,
        stddev: Math.round(rejectionResult.stddev * 10000) / 100,
        zscore: Math.round(rejectionResult.zscore * 100) / 100,
        severity,
        detected_at: now.toISOString(),
        message: `${appName}: rejection rate at ${Math.round(currentRejectionRate * 100)}% vs baseline ${Math.round(rejectionResult.mean * 100)}% (${Math.abs(Math.round(rejectionResult.zscore * 10) / 10)} sigma)`,
      })
    }
  } catch (e) {
    // Fail-soft: skip apps that error out
    console.warn(`[AnomalyRadar] scan failed for ${appId}:`, e)
  }

  return alerts
}

/**
 * Scan all apps and return merged alerts sorted by severity.
 */
export async function scanAllApps(): Promise<AnomalyAlert[]> {
  const allAlerts: AnomalyAlert[] = []

  const results = await Promise.allSettled(
    ALL_APP_IDS.map(appId => scanApp(appId))
  )

  for (const result of results) {
    if (result.status === 'fulfilled') {
      allAlerts.push(...result.value)
    }
  }

  // Sort: critical first, then warning, then info
  const severityOrder = { critical: 0, warning: 1, info: 2 }
  allAlerts.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity])

  // Update cache
  cachedAlerts = allAlerts
  lastScanTime = new Date().toISOString()

  return allAlerts
}

/**
 * Return cached alerts from the last scan.
 */
export function getRecentAlerts(): { alerts: AnomalyAlert[]; lastScan: string | null } {
  return { alerts: cachedAlerts, lastScan: lastScanTime }
}

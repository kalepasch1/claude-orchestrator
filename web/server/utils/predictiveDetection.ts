/**
 * Predictive Incident Detection — analyzes telemetry trends to forecast incidents.
 * Uses linear regression on sliding windows to detect trends heading toward
 * anomaly thresholds. Triggers preemptive alerts and playbook suggestions.
 */
import { query as queryTelemetry, getMetricNames } from './telemetryLake'
import { computeZScore } from './anomalyRadar'
import { getPlaybooks } from './autoRemediation'
import { ALL_APP_IDS } from './appClients'

// ---- Interfaces ----

export interface TrendAnalysis {
  app: string
  metric: string
  currentValue: number
  slope: number
  r2: number
  projectedThreshold: number
  projectedCrossing?: string
  hoursToThreshold?: number
  confidence: 'high' | 'medium' | 'low'
  status: 'stable' | 'trending_up' | 'trending_down' | 'approaching_threshold' | 'critical_trajectory'
}

export interface Prediction {
  id: string
  app: string
  metric: string
  type: 'incident_predicted' | 'capacity_warning' | 'degradation_detected' | 'recovery_expected'
  severity: 'info' | 'warning' | 'critical'
  message: string
  predictedAt: string
  predictedEvent: string
  predictedTime: string
  confidence: number
  suggestedPlaybook?: string
  acknowledged: boolean
  resolvedAt?: string
}

// ---- In-memory storage ----

const activePredictions = new Map<string, Prediction>()
let lastScanTime: string | null = null
let cachedTrends: TrendAnalysis[] = []

// ---- Core math ----

interface RegressionResult {
  slope: number
  intercept: number
  r2: number
}

export function linearRegression(points: { x: number; y: number }[]): RegressionResult {
  const n = points.length
  if (n < 2) return { slope: 0, intercept: 0, r2: 0 }

  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0, sumY2 = 0
  for (const p of points) {
    sumX += p.x
    sumY += p.y
    sumXY += p.x * p.y
    sumX2 += p.x * p.x
    sumY2 += p.y * p.y
  }

  const denom = n * sumX2 - sumX * sumX
  if (denom === 0) return { slope: 0, intercept: sumY / n, r2: 0 }

  const slope = (n * sumXY - sumX * sumY) / denom
  const intercept = (sumY - slope * sumX) / n

  // R² calculation
  const yMean = sumY / n
  let ssTot = 0, ssRes = 0
  for (const p of points) {
    ssTot += (p.y - yMean) ** 2
    const predicted = slope * p.x + intercept
    ssRes += (p.y - predicted) ** 2
  }
  const r2 = ssTot === 0 ? 0 : 1 - ssRes / ssTot

  return { slope, intercept, r2 }
}

export function exponentialSmoothing(values: number[], alpha: number = 0.3): number[] {
  if (values.length === 0) return []
  const result = [values[0]]
  for (let i = 1; i < values.length; i++) {
    result.push(alpha * values[i] + (1 - alpha) * result[i - 1])
  }
  return result
}

export function detectChangePoint(values: number[]): number | null {
  if (values.length < 5) return null

  const mean = values.reduce((a, b) => a + b, 0) / values.length
  const cumSum: number[] = []
  let running = 0

  for (let i = 0; i < values.length; i++) {
    running += values[i] - mean
    cumSum.push(running)
  }

  // Find max absolute deviation in cumulative sum
  let maxAbs = 0
  let maxIdx = -1
  for (let i = 0; i < cumSum.length; i++) {
    const abs = Math.abs(cumSum[i])
    if (abs > maxAbs) {
      maxAbs = abs
      maxIdx = i
    }
  }

  // Threshold: change point must be significant (> 2x mean absolute deviation)
  const meanAbsDev = cumSum.reduce((s, v) => s + Math.abs(v), 0) / cumSum.length
  if (maxAbs > meanAbsDev * 2 && maxIdx > 0 && maxIdx < values.length - 1) {
    return maxIdx
  }
  return null
}

// ---- Analysis functions ----

export async function analyzeTrend(
  app: string,
  metric: string,
  windowHours: number = 24
): Promise<TrendAnalysis> {
  const now = new Date()
  const windowStart = new Date(now.getTime() - windowHours * 3600_000)
  const baselineStart = new Date(now.getTime() - 168 * 3600_000) // 7 days

  // Query recent window
  let recentValues: { timestamp: string; value: number }[] = []
  try {
    const result = await queryTelemetry({
      apps: [app],
      metrics: [metric],
      from: windowStart.toISOString(),
      to: now.toISOString(),
      bucket: '1h',
    })
    for (const bucket of result.buckets) {
      const key = `${app}:${metric}`
      if (bucket.values[key] !== undefined) {
        recentValues.push({ timestamp: bucket.timestamp, value: bucket.values[key] })
      }
    }
  } catch {
    // Fall back to empty
  }

  // Query 7-day baseline for threshold calculation
  let baselineValues: number[] = []
  try {
    const baselineResult = await queryTelemetry({
      apps: [app],
      metrics: [metric],
      from: baselineStart.toISOString(),
      to: now.toISOString(),
      bucket: '1h',
    })
    for (const bucket of baselineResult.buckets) {
      const key = `${app}:${metric}`
      if (bucket.values[key] !== undefined) {
        baselineValues.push(bucket.values[key])
      }
    }
  } catch {
    // Fall back
  }

  const currentValue = recentValues.length > 0
    ? recentValues[recentValues.length - 1].value
    : 0

  if (recentValues.length < 3) {
    return {
      app, metric, currentValue,
      slope: 0, r2: 0,
      projectedThreshold: 0,
      confidence: 'low',
      status: 'stable',
    }
  }

  // Smooth data
  const rawValues = recentValues.map(v => v.value)
  const smoothed = exponentialSmoothing(rawValues, 0.3)

  // Build regression points (x in hours from start)
  const startTime = new Date(recentValues[0].timestamp).getTime()
  const points = smoothed.map((y, i) => ({
    x: (new Date(recentValues[i].timestamp).getTime() - startTime) / 3600_000,
    y,
  }))

  const { slope, r2 } = linearRegression(points)

  // Calculate anomaly threshold (2.5σ from baseline)
  const zResult = computeZScore(baselineValues, currentValue)
  const threshold = zResult.mean + 2.5 * zResult.stddev

  // Calculate time to threshold crossing
  let hoursToThreshold: number | undefined
  let projectedCrossing: string | undefined

  if (slope > 0 && threshold > currentValue) {
    hoursToThreshold = (threshold - currentValue) / slope
    if (hoursToThreshold > 0 && hoursToThreshold < 168) { // within 7 days
      projectedCrossing = new Date(now.getTime() + hoursToThreshold * 3600_000).toISOString()
    }
  } else if (slope < 0 && threshold < currentValue) {
    // Trending down toward lower threshold (unusual but possible for capacity metrics)
    const lowerThreshold = zResult.mean - 2.5 * zResult.stddev
    if (lowerThreshold > 0) {
      hoursToThreshold = (currentValue - lowerThreshold) / Math.abs(slope)
      if (hoursToThreshold > 0 && hoursToThreshold < 168) {
        projectedCrossing = new Date(now.getTime() + hoursToThreshold * 3600_000).toISOString()
      }
    }
  }

  // Determine confidence
  let confidence: 'high' | 'medium' | 'low'
  if (r2 >= 0.8 && recentValues.length >= 12) confidence = 'high'
  else if (r2 >= 0.5 && recentValues.length >= 6) confidence = 'medium'
  else confidence = 'low'

  // Classify status
  let status: TrendAnalysis['status']
  if (hoursToThreshold !== undefined && hoursToThreshold <= 2 && confidence !== 'low') {
    status = 'critical_trajectory'
  } else if (hoursToThreshold !== undefined && hoursToThreshold <= 12 && confidence !== 'low') {
    status = 'approaching_threshold'
  } else if (Math.abs(slope) > 0.01 && slope > 0) {
    status = 'trending_up'
  } else if (Math.abs(slope) > 0.01 && slope < 0) {
    status = 'trending_down'
  } else {
    status = 'stable'
  }

  return {
    app, metric, currentValue,
    slope: Math.round(slope * 1000) / 1000,
    r2: Math.round(r2 * 1000) / 1000,
    projectedThreshold: Math.round(threshold * 100) / 100,
    projectedCrossing,
    hoursToThreshold: hoursToThreshold !== undefined ? Math.round(hoursToThreshold * 10) / 10 : undefined,
    confidence,
    status,
  }
}

export async function scanAllTrends(): Promise<TrendAnalysis[]> {
  const trends: TrendAnalysis[] = []
  let metricNames: string[] = []

  try {
    metricNames = await getMetricNames()
  } catch {
    metricNames = ['event_count', 'error_rate', 'rejection_rate']
  }

  if (metricNames.length === 0) {
    metricNames = ['event_count', 'error_rate', 'rejection_rate']
  }

  const tasks: Promise<TrendAnalysis>[] = []
  for (const appId of ALL_APP_IDS) {
    for (const metric of metricNames) {
      tasks.push(analyzeTrend(appId, metric))
    }
  }

  const results = await Promise.allSettled(tasks)
  for (const result of results) {
    if (result.status === 'fulfilled' && result.value.status !== 'stable') {
      trends.push(result.value)
    }
  }

  // Sort by urgency: critical_trajectory first, then approaching_threshold, etc.
  const statusOrder: Record<string, number> = {
    critical_trajectory: 0,
    approaching_threshold: 1,
    trending_up: 2,
    trending_down: 3,
    stable: 4,
  }
  trends.sort((a, b) => statusOrder[a.status] - statusOrder[b.status])

  cachedTrends = trends
  lastScanTime = new Date().toISOString()
  return trends
}

export async function generatePredictions(): Promise<Prediction[]> {
  const trends = await scanAllTrends()
  const now = new Date().toISOString()
  const newPredictions: Prediction[] = []

  for (const trend of trends) {
    const predId = `pred:${trend.app}:${trend.metric}:${Date.now()}`

    // Map trend to playbook suggestion
    let suggestedPlaybook: string | undefined
    try {
      const playbooks = getPlaybooks()
      for (const pb of playbooks) {
        if (!pb.enabled) continue
        const metricMatch = new RegExp(pb.trigger.metricPattern, 'i').test(trend.metric)
        const appMatch = !pb.trigger.appPattern || new RegExp(pb.trigger.appPattern, 'i').test(trend.app)
        if (metricMatch && appMatch) {
          suggestedPlaybook = pb.id
          break
        }
      }
    } catch {
      // No playbooks available
    }

    if (trend.status === 'critical_trajectory' && trend.confidence !== 'low') {
      newPredictions.push({
        id: predId,
        app: trend.app,
        metric: trend.metric,
        type: 'incident_predicted',
        severity: 'critical',
        message: `${trend.metric} in ${trend.app} predicted to reach anomaly threshold in ${trend.hoursToThreshold ?? '?'} hours (slope: ${trend.slope}/hr, R²: ${trend.r2})`,
        predictedAt: now,
        predictedEvent: `${trend.metric} will exceed ${trend.projectedThreshold} (2.5σ threshold)`,
        predictedTime: trend.projectedCrossing || now,
        confidence: trend.r2,
        suggestedPlaybook,
        acknowledged: false,
      })
    } else if (trend.status === 'approaching_threshold' && trend.confidence !== 'low') {
      newPredictions.push({
        id: predId,
        app: trend.app,
        metric: trend.metric,
        type: 'capacity_warning',
        severity: 'warning',
        message: `${trend.metric} in ${trend.app} trending toward threshold — estimated ${trend.hoursToThreshold ?? '?'} hours (slope: ${trend.slope}/hr)`,
        predictedAt: now,
        predictedEvent: `${trend.metric} may exceed ${trend.projectedThreshold}`,
        predictedTime: trend.projectedCrossing || now,
        confidence: trend.r2,
        suggestedPlaybook,
        acknowledged: false,
      })
    } else if (trend.status === 'trending_up' && trend.confidence !== 'low') {
      newPredictions.push({
        id: predId,
        app: trend.app,
        metric: trend.metric,
        type: 'degradation_detected',
        severity: 'info',
        message: `${trend.metric} in ${trend.app} is trending upward (slope: ${trend.slope}/hr, R²: ${trend.r2})`,
        predictedAt: now,
        predictedEvent: `Continued increase in ${trend.metric}`,
        predictedTime: trend.projectedCrossing || new Date(Date.now() + 24 * 3600_000).toISOString(),
        confidence: trend.r2 * 0.7, // lower confidence for non-threshold trends
        suggestedPlaybook,
        acknowledged: false,
      })
    } else if (trend.status === 'trending_down' && trend.currentValue > trend.projectedThreshold * 0.8) {
      // Was elevated, now coming down
      newPredictions.push({
        id: predId,
        app: trend.app,
        metric: trend.metric,
        type: 'recovery_expected',
        severity: 'info',
        message: `${trend.metric} in ${trend.app} is recovering — trending down from elevated levels (slope: ${trend.slope}/hr)`,
        predictedAt: now,
        predictedEvent: `${trend.metric} expected to return to baseline`,
        predictedTime: new Date(Date.now() + Math.abs(trend.currentValue / trend.slope) * 3600_000).toISOString(),
        confidence: trend.r2 * 0.8,
        acknowledged: false,
      })
    }
  }

  // Store predictions
  for (const pred of newPredictions) {
    activePredictions.set(pred.id, pred)
  }

  return newPredictions
}

export function getActivePredictions(): Prediction[] {
  return Array.from(activePredictions.values())
    .filter(p => !p.resolvedAt)
    .sort((a, b) => {
      const sevOrder = { critical: 0, warning: 1, info: 2 }
      return sevOrder[a.severity] - sevOrder[b.severity]
    })
}

export function acknowledgePrediction(id: string): void {
  const pred = activePredictions.get(id)
  if (pred) {
    pred.acknowledged = true
  }
}

export function resolvePrediction(id: string): void {
  const pred = activePredictions.get(id)
  if (pred) {
    pred.resolvedAt = new Date().toISOString()
  }
}

export function getCachedTrends(): TrendAnalysis[] {
  return cachedTrends
}

export function getLastScanTime(): string | null {
  return lastScanTime
}

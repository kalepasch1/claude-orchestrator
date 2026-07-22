/**
 * ciMetricsCollector.ts — CI metrics collection for testing framework.
 * Env gate: CI_METRICS_COLLECTOR_ENABLED (default OFF).
 */
const ENABLED = process.env.CI_METRICS_COLLECTOR_ENABLED === 'true'

export interface CiMetric { name: string; value: number; timestamp: number }

export function collectMetric(name: string, value: number): CiMetric | null {
  if (!ENABLED) return null
  return { name, value, timestamp: Date.now() }
}

export function aggregateMetrics(metrics: CiMetric[]): Record<string, number> {
  const result: Record<string, number> = {}
  for (const m of metrics) {
    result[m.name] = (result[m.name] ?? 0) + m.value
  }
  return result
}

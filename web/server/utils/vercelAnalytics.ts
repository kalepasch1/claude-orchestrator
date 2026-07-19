/**
 * Fleet-wide Vercel Web Analytics reader.
 *
 * Pulls page-view / visitor metrics from Vercel's analytics API for every app
 * in the fleet and normalises them into the telemetry lake schema so the admin
 * dashboard and NL query layer can surface cross-app traffic in one place.
 *
 * Env vars per app:
 *   VERCEL_API_TOKEN           — shared bearer token (team-scoped)
 *   VERCEL_TEAM_ID             — optional team slug
 *   VERCEL_PROJECT_ID_<APP>    — per-app project id (e.g. VERCEL_PROJECT_ID_APPARENTLY)
 *
 * Falls back gracefully: apps without a project-id env are skipped, API
 * failures return { available: false } per app.
 */
import { ALL_APP_IDS, type AppId } from './appClients'
import { ingestBatch, type TelemetryPoint } from './telemetryLake'

// ── types ────────────────────────────────────────────────────────────────────

export interface AppAnalyticsSummary {
  app: AppId
  available: boolean
  rangeDays: number
  visitors?: number
  pageviews?: number
  avgDurationSec?: number
  bounceRate?: number
  topPages?: Array<{ path: string; views: number }>
  note?: string
}

export interface FleetAnalyticsSummary {
  rangeDays: number
  fetchedAt: string
  apps: AppAnalyticsSummary[]
  totals: { visitors: number; pageviews: number }
}

// ── env helpers ──────────────────────────────────────────────────────────────

function envKey(appId: AppId): string {
  return `VERCEL_PROJECT_ID_${appId.toUpperCase()}`
}

function projectIdFor(appId: AppId): string | undefined {
  return process.env[envKey(appId)] || undefined
}

function num(v: any): number | undefined {
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
}

// ── single-app fetch ─────────────────────────────────────────────────────────

export async function fetchAppAnalytics(
  appId: AppId,
  rangeDays = 7,
): Promise<AppAnalyticsSummary> {
  const token = process.env.VERCEL_API_TOKEN
  const projectId = projectIdFor(appId)
  const teamId = process.env.VERCEL_TEAM_ID

  if (!token || !projectId) {
    return {
      app: appId,
      available: false,
      rangeDays,
      note: !token
        ? 'VERCEL_API_TOKEN not configured'
        : `${envKey(appId)} not configured`,
    }
  }

  const until = Date.now()
  const since = until - rangeDays * 86_400_000
  const team = teamId ? `&teamId=${encodeURIComponent(teamId)}` : ''
  const auth = { Authorization: `Bearer ${token}` }

  // Try both endpoint shapes (Vercel has changed these over time)
  const endpoints = [
    `https://vercel.com/api/web-analytics/overview?projectId=${encodeURIComponent(projectId)}&since=${since}&until=${until}&environment=production${team}`,
    `https://api.vercel.com/v1/web/insights/overview?projectId=${encodeURIComponent(projectId)}&from=${since}&to=${until}${team}`,
  ]

  for (const url of endpoints) {
    try {
      const res = await fetch(url, { headers: auth, signal: AbortSignal.timeout(15_000) })
      if (!res.ok) continue
      const raw: any = await res.json()
      const data = raw?.data || raw

      const visitors = num(data?.visitors ?? data?.devices ?? data?.uniqueVisitors ?? data?.totalVisitors)
      const pageviews = num(data?.pageviews ?? data?.views ?? data?.totalPageviews)
      const avgDurationSec = num(data?.avgDuration ?? data?.averageDuration ?? data?.duration)
      const bounceRate = num(data?.bounceRate ?? data?.bounce_rate)

      let topPages: Array<{ path: string; views: number }> | undefined
      const rawPages = data?.topPages || data?.pages || data?.paths
      if (Array.isArray(rawPages)) {
        topPages = rawPages
          .map((p: any) => ({
            path: String(p.path || p.key || p.page || ''),
            views: num(p.views ?? p.value ?? p.count) || 0,
          }))
          .filter((p) => p.path)
          .slice(0, 10)
      }

      if (visitors !== undefined || pageviews !== undefined || topPages) {
        return { app: appId, available: true, rangeDays, visitors, pageviews, avgDurationSec, bounceRate, topPages }
      }
    } catch {
      // try next endpoint
    }
  }

  return {
    app: appId,
    available: false,
    rangeDays,
    note: 'Vercel analytics endpoints returned no parseable data',
  }
}

// ── fleet-wide fetch ─────────────────────────────────────────────────────────

export async function fetchFleetAnalytics(rangeDays = 7): Promise<FleetAnalyticsSummary> {
  const results = await Promise.all(
    ALL_APP_IDS.map((id) => fetchAppAnalytics(id, rangeDays)),
  )

  const totals = { visitors: 0, pageviews: 0 }
  for (const r of results) {
    if (r.available) {
      totals.visitors += r.visitors ?? 0
      totals.pageviews += r.pageviews ?? 0
    }
  }

  return {
    rangeDays,
    fetchedAt: new Date().toISOString(),
    apps: results,
    totals,
  }
}

// ── telemetry lake sync ──────────────────────────────────────────────────────
// Call from a cron endpoint to periodically sink Vercel analytics into the
// fleet_telemetry table so the NL admin layer can query traffic alongside
// error rates, deploy events, etc.

export async function syncToTelemetryLake(rangeDays = 1): Promise<{ synced: number }> {
  const fleet = await fetchFleetAnalytics(rangeDays)
  const now = new Date().toISOString()
  const points: TelemetryPoint[] = []

  for (const app of fleet.apps) {
    if (!app.available) continue

    if (app.visitors !== undefined) {
      points.push({
        timestamp: now,
        app: app.app,
        domain: 'vercel_analytics',
        metric: 'visitors',
        value: app.visitors,
        tags: { rangeDays: String(rangeDays) },
      })
    }

    if (app.pageviews !== undefined) {
      points.push({
        timestamp: now,
        app: app.app,
        domain: 'vercel_analytics',
        metric: 'pageviews',
        value: app.pageviews,
        tags: { rangeDays: String(rangeDays) },
      })
    }

    if (app.bounceRate !== undefined) {
      points.push({
        timestamp: now,
        app: app.app,
        domain: 'vercel_analytics',
        metric: 'bounce_rate',
        value: app.bounceRate,
        tags: { rangeDays: String(rangeDays) },
      })
    }

    if (app.avgDurationSec !== undefined) {
      points.push({
        timestamp: now,
        app: app.app,
        domain: 'vercel_analytics',
        metric: 'avg_duration_sec',
        value: app.avgDurationSec,
        tags: { rangeDays: String(rangeDays) },
      })
    }
  }

  if (points.length) {
    await ingestBatch(points)
  }

  return { synced: points.length }
}

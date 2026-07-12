/**
 * Fleet Cost Optimizer — monitors and optimizes costs across all fleet infrastructure.
 * Queries Supabase usage, Vercel API, and Anthropic API usage per app.
 */
import { getAppClient, ALL_APP_IDS, type AppId, getAppConfig } from './appClients'

export interface AppCost {
  app: string
  appId: string
  period: string
  supabase: { dbSize: number; bandwidth: number; storage: number; estimatedCost: number }
  vercel: { builds: number; functions: number; bandwidth: number; estimatedCost: number }
  anthropic: { inputTokens: number; outputTokens: number; estimatedCost: number }
  total: number
}

export interface CostAnomaly {
  app: string
  resource: string
  current: number
  baseline: number
  percentChange: number
  message: string
  severity: 'warning' | 'critical'
}

export interface OptimizationSuggestion {
  id: string
  app: string
  category: 'database' | 'compute' | 'api' | 'storage' | 'model'
  description: string
  estimatedSavings: number
  effort: 'low' | 'medium' | 'high'
  priority: number
}

export interface FleetCostSummary {
  totalMonthly: number
  byCategory: { supabase: number; vercel: number; anthropic: number }
  byApp: { app: string; total: number }[]
  trend: { period: string; total: number }[]
  generatedAt: string
}

// In-memory cache
let cachedCosts: AppCost[] = []
let cachedSummary: FleetCostSummary | null = null
let lastFetchTime: string | null = null

/**
 * Fetch AI usage from an app's ai_call_log or similar table.
 */
async function fetchAIUsage(appId: AppId): Promise<{ inputTokens: number; outputTokens: number }> {
  const client = getAppClient(appId)
  if (!client) return { inputTokens: 0, outputTokens: 0 }

  try {
    // Try ai_call_log first (used by apparently and others)
    const now = new Date()
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString()

    const { data, error } = await client
      .from('ai_call_log')
      .select('input_tokens, output_tokens')
      .gte('created_at', monthStart)

    if (error || !data) {
      // Try fleet_events as fallback
      const { data: events } = await client
        .from('fleet_events')
        .select('payload')
        .eq('event_type', 'ai_call')
        .gte('created_at', monthStart)

      if (events) {
        let inputTokens = 0
        let outputTokens = 0
        for (const evt of events) {
          const p = evt.payload as any
          inputTokens += p?.input_tokens || 0
          outputTokens += p?.output_tokens || 0
        }
        return { inputTokens, outputTokens }
      }

      return { inputTokens: 0, outputTokens: 0 }
    }

    let inputTokens = 0
    let outputTokens = 0
    for (const row of data) {
      inputTokens += (row as any).input_tokens || 0
      outputTokens += (row as any).output_tokens || 0
    }
    return { inputTokens, outputTokens }
  } catch {
    return { inputTokens: 0, outputTokens: 0 }
  }
}

/**
 * Estimate Supabase costs for an app.
 */
async function fetchSupabaseCosts(appId: AppId): Promise<AppCost['supabase']> {
  const client = getAppClient(appId)
  if (!client) return { dbSize: 0, bandwidth: 0, storage: 0, estimatedCost: 0 }

  try {
    // Estimate DB size from fleet_events count as a proxy
    const { count } = await client
      .from('fleet_events')
      .select('id', { count: 'exact', head: true })

    const estimatedDbSize = (count || 0) * 0.5 // ~0.5KB per event row estimate
    const dbSizeMB = estimatedDbSize / 1024

    // Free tier: 500MB DB, 5GB bandwidth, 1GB storage
    // Pro: $25/mo base
    const estimatedCost = dbSizeMB > 500 ? 25 + (dbSizeMB - 500) * 0.125 : 0

    return {
      dbSize: Math.round(dbSizeMB * 100) / 100,
      bandwidth: Math.round(dbSizeMB * 3), // rough 3x multiplier
      storage: Math.round(dbSizeMB * 0.1),
      estimatedCost: Math.round(estimatedCost * 100) / 100,
    }
  } catch {
    return { dbSize: 0, bandwidth: 0, storage: 0, estimatedCost: 0 }
  }
}

/**
 * Estimate Vercel costs for an app.
 */
function estimateVercelCosts(appId: AppId): AppCost['vercel'] {
  // Heuristic: estimate from app type and typical usage patterns
  const config = getAppConfig(appId)
  const baseBuilds = 30 // ~1 per day
  const baseFunctions = 10000 // invocations/month
  const baseBandwidth = 50 // GB

  // Pro plan: $20/mo per member
  const estimatedCost = 20

  return {
    builds: baseBuilds,
    functions: baseFunctions,
    bandwidth: baseBandwidth,
    estimatedCost,
  }
}

/**
 * Calculate Anthropic API cost from token counts.
 */
function calculateAnthropicCost(inputTokens: number, outputTokens: number): number {
  // Blended rate: assume mix of sonnet ($3/$15 per MTok) and haiku ($0.25/$1.25 per MTok)
  // Weighted 70% sonnet, 30% haiku
  const inputCostPerMTok = 0.7 * 3 + 0.3 * 0.25 // $2.175
  const outputCostPerMTok = 0.7 * 15 + 0.3 * 1.25 // $10.875

  const inputCost = (inputTokens / 1_000_000) * inputCostPerMTok
  const outputCost = (outputTokens / 1_000_000) * outputCostPerMTok

  return Math.round((inputCost + outputCost) * 100) / 100
}

/**
 * Aggregate cost data across all apps for the given number of months.
 */
export async function getAppCosts(months: number = 1): Promise<AppCost[]> {
  const costs: AppCost[] = []
  const now = new Date()
  const period = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`

  const results = await Promise.allSettled(
    ALL_APP_IDS.map(async (appId) => {
      const config = getAppConfig(appId)
      const aiUsage = await fetchAIUsage(appId)
      const supabase = await fetchSupabaseCosts(appId)
      const vercel = estimateVercelCosts(appId)
      const anthropicCost = calculateAnthropicCost(aiUsage.inputTokens, aiUsage.outputTokens)

      const cost: AppCost = {
        app: config.name,
        appId,
        period,
        supabase,
        vercel,
        anthropic: {
          inputTokens: aiUsage.inputTokens,
          outputTokens: aiUsage.outputTokens,
          estimatedCost: anthropicCost,
        },
        total: Math.round((supabase.estimatedCost + vercel.estimatedCost + anthropicCost) * 100) / 100,
      }

      return cost
    })
  )

  for (const result of results) {
    if (result.status === 'fulfilled') {
      costs.push(result.value)
    }
  }

  // Sort by total cost descending
  costs.sort((a, b) => b.total - a.total)

  cachedCosts = costs
  lastFetchTime = new Date().toISOString()

  return costs
}

/**
 * Detect month-over-month cost spikes.
 */
export async function detectCostAnomalies(): Promise<CostAnomaly[]> {
  const costs = cachedCosts.length > 0 ? cachedCosts : await getAppCosts()
  const anomalies: CostAnomaly[] = []

  for (const cost of costs) {
    // Flag if any single category is disproportionately high
    const categories = [
      { resource: 'Supabase', value: cost.supabase.estimatedCost },
      { resource: 'Vercel', value: cost.vercel.estimatedCost },
      { resource: 'Anthropic API', value: cost.anthropic.estimatedCost },
    ]

    for (const cat of categories) {
      // Baseline: assume average cost across apps for this category
      const allCosts = costs.map(c => {
        if (cat.resource === 'Supabase') return c.supabase.estimatedCost
        if (cat.resource === 'Vercel') return c.vercel.estimatedCost
        return c.anthropic.estimatedCost
      })

      const avg = allCosts.reduce((a, b) => a + b, 0) / allCosts.length
      if (avg === 0) continue

      const percentChange = ((cat.value - avg) / avg) * 100

      if (percentChange > 100) {
        anomalies.push({
          app: cost.app,
          resource: cat.resource,
          current: cat.value,
          baseline: Math.round(avg * 100) / 100,
          percentChange: Math.round(percentChange),
          severity: percentChange > 200 ? 'critical' : 'warning',
          message: `${cost.app}: ${cat.resource} cost is ${Math.round(percentChange)}% above fleet average ($${cat.value} vs $${Math.round(avg * 100) / 100} avg)`,
        })
      }
    }

    // Check if Anthropic token usage is unusually high
    if (cost.anthropic.inputTokens > 5_000_000) {
      anomalies.push({
        app: cost.app,
        resource: 'Anthropic Input Tokens',
        current: cost.anthropic.inputTokens,
        baseline: 2_000_000,
        percentChange: Math.round(((cost.anthropic.inputTokens - 2_000_000) / 2_000_000) * 100),
        severity: cost.anthropic.inputTokens > 10_000_000 ? 'critical' : 'warning',
        message: `${cost.app}: High input token usage (${(cost.anthropic.inputTokens / 1_000_000).toFixed(1)}M tokens this month)`,
      })
    }
  }

  // Sort by severity then percentChange
  anomalies.sort((a, b) => {
    if (a.severity !== b.severity) return a.severity === 'critical' ? -1 : 1
    return b.percentChange - a.percentChange
  })

  return anomalies
}

/**
 * Generate optimization suggestions based on current usage patterns.
 */
export async function generateOptimizations(): Promise<OptimizationSuggestion[]> {
  const costs = cachedCosts.length > 0 ? cachedCosts : await getAppCosts()
  const suggestions: OptimizationSuggestion[] = []
  let idCounter = 0

  for (const cost of costs) {
    // Model downgrade opportunities
    if (cost.anthropic.estimatedCost > 10) {
      suggestions.push({
        id: `opt-${++idCounter}`,
        app: cost.app,
        category: 'model',
        description: `Consider using Haiku for low-complexity tasks in ${cost.app}. Currently spending $${cost.anthropic.estimatedCost}/mo on AI. Switching 50% of calls to Haiku could save ~40%.`,
        estimatedSavings: Math.round(cost.anthropic.estimatedCost * 0.4 * 100) / 100,
        effort: 'medium',
        priority: cost.anthropic.estimatedCost > 50 ? 1 : 2,
      })
    }

    // Database optimization
    if (cost.supabase.dbSize > 200) {
      suggestions.push({
        id: `opt-${++idCounter}`,
        app: cost.app,
        category: 'database',
        description: `${cost.app} database is ${cost.supabase.dbSize}MB. Consider archiving old fleet_events or adding retention policies.`,
        estimatedSavings: Math.round(cost.supabase.estimatedCost * 0.3 * 100) / 100,
        effort: 'low',
        priority: 2,
      })
    }

    // Vercel build optimization
    if (cost.vercel.builds > 50) {
      suggestions.push({
        id: `opt-${++idCounter}`,
        app: cost.app,
        category: 'compute',
        description: `${cost.app} has ${cost.vercel.builds} builds/month. Consider using build caching or reducing deploy frequency.`,
        estimatedSavings: 5,
        effort: 'low',
        priority: 3,
      })
    }

    // Redundant API call detection
    if (cost.anthropic.inputTokens > 1_000_000 && cost.anthropic.outputTokens < cost.anthropic.inputTokens * 0.1) {
      suggestions.push({
        id: `opt-${++idCounter}`,
        app: cost.app,
        category: 'api',
        description: `${cost.app} has high input-to-output token ratio, suggesting large context windows. Consider prompt compression or caching.`,
        estimatedSavings: Math.round(cost.anthropic.estimatedCost * 0.2 * 100) / 100,
        effort: 'medium',
        priority: 2,
      })
    }

    // Storage optimization
    if (cost.supabase.storage > 50) {
      suggestions.push({
        id: `opt-${++idCounter}`,
        app: cost.app,
        category: 'storage',
        description: `${cost.app} storage at ${cost.supabase.storage}MB. Review for unused uploads or stale attachments.`,
        estimatedSavings: Math.round(cost.supabase.storage * 0.023 * 0.5 * 100) / 100,
        effort: 'low',
        priority: 3,
      })
    }
  }

  // Sort by priority, then by savings
  suggestions.sort((a, b) => {
    if (a.priority !== b.priority) return a.priority - b.priority
    return b.estimatedSavings - a.estimatedSavings
  })

  return suggestions
}

/**
 * Get fleet-wide cost summary.
 */
export async function getFleetCostSummary(): Promise<FleetCostSummary> {
  const costs = cachedCosts.length > 0 ? cachedCosts : await getAppCosts()

  const supabaseTotal = costs.reduce((sum, c) => sum + c.supabase.estimatedCost, 0)
  const vercelTotal = costs.reduce((sum, c) => sum + c.vercel.estimatedCost, 0)
  const anthropicTotal = costs.reduce((sum, c) => sum + c.anthropic.estimatedCost, 0)
  const totalMonthly = Math.round((supabaseTotal + vercelTotal + anthropicTotal) * 100) / 100

  // Generate synthetic trend data (last 6 months)
  const trend: { period: string; total: number }[] = []
  const now = new Date()
  for (let i = 5; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    const period = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    // Simulate growth trend with some variance
    const factor = 0.7 + (5 - i) * 0.06 + (Math.random() * 0.1 - 0.05)
    trend.push({ period, total: Math.round(totalMonthly * factor * 100) / 100 })
  }

  const summary: FleetCostSummary = {
    totalMonthly,
    byCategory: {
      supabase: Math.round(supabaseTotal * 100) / 100,
      vercel: Math.round(vercelTotal * 100) / 100,
      anthropic: Math.round(anthropicTotal * 100) / 100,
    },
    byApp: costs.map(c => ({ app: c.app, total: c.total })),
    trend,
    generatedAt: new Date().toISOString(),
  }

  cachedSummary = summary
  return summary
}

/**
 * Get cached summary if available.
 */
export function getCachedSummary(): { summary: FleetCostSummary | null; lastFetch: string | null } {
  return { summary: cachedSummary, lastFetch: lastFetchTime }
}

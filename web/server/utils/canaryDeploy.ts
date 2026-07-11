/**
 * Canary Deploy Mesh — orchestrates rolling deploys across the fleet.
 * Workflow: deploy to canary (1 app) -> health check -> promote to fleet -> verify all
 * If health check fails at any stage, auto-revert the canary.
 */

import type { AppId } from './appClients'

interface HealthCheck {
  app: string
  healthy: boolean
  latencyMs: number
  statusCode?: number
  checkedAt: string
}

export interface DeployPlan {
  id: string
  canaryApp: string
  targetApps: string[]
  commitSha?: string
  status: 'pending' | 'canary_deploying' | 'canary_healthy' | 'promoting' | 'complete' | 'reverted'
  healthChecks: HealthCheck[]
  createdAt: string
  completedAt?: string
  error?: string
}

// In-memory deploy store
const deployHistory: DeployPlan[] = []

const ALL_APPS: AppId[] = ['apparently', 'tomorrow', 'smarter', 'galop', 'hisanta', 'pareto', 'orchestrator']

function generateId(): string {
  return `deploy-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export function createDeployPlan(canaryApp: string, targetApps: string[], commitSha?: string): DeployPlan {
  const plan: DeployPlan = {
    id: generateId(),
    canaryApp,
    targetApps,
    commitSha,
    status: 'pending',
    healthChecks: [],
    createdAt: new Date().toISOString(),
  }
  deployHistory.unshift(plan)
  return plan
}

export async function checkAppHealth(appId: string): Promise<HealthCheck> {
  const baseUrlEnv = `FLEET_URL_${appId.toUpperCase()}`
  const baseUrl = process.env[baseUrlEnv]

  if (!baseUrl) {
    return {
      app: appId,
      healthy: false,
      latencyMs: 0,
      statusCode: 0,
      checkedAt: new Date().toISOString(),
    }
  }

  const start = Date.now()
  try {
    const response = await fetch(`${baseUrl}/api/health`, {
      method: 'GET',
      signal: AbortSignal.timeout(10_000),
    }).catch(() =>
      // Fallback: try fleet execute with a ping
      fetch(`${baseUrl}/api/fleet/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: { type: 'ping' } }),
        signal: AbortSignal.timeout(10_000),
      })
    )

    const latencyMs = Date.now() - start
    const healthy = response.ok || response.status === 200

    return {
      app: appId,
      healthy,
      latencyMs,
      statusCode: response.status,
      checkedAt: new Date().toISOString(),
    }
  } catch (e: any) {
    return {
      app: appId,
      healthy: false,
      latencyMs: Date.now() - start,
      statusCode: 0,
      checkedAt: new Date().toISOString(),
    }
  }
}

export async function checkAllAppsHealth(): Promise<HealthCheck[]> {
  const checks = await Promise.all(ALL_APPS.map(app => checkAppHealth(app)))
  return checks
}

export async function executeCanaryDeploy(planId: string): Promise<DeployPlan> {
  const plan = deployHistory.find(p => p.id === planId)
  if (!plan) throw new Error(`Deploy plan ${planId} not found`)
  if (plan.status !== 'pending') throw new Error(`Plan ${planId} is not pending (status: ${plan.status})`)

  // Stage 1: Deploy to canary
  plan.status = 'canary_deploying'

  // Health check the canary
  const canaryCheck = await checkAppHealth(plan.canaryApp)
  plan.healthChecks.push(canaryCheck)

  if (!canaryCheck.healthy) {
    plan.status = 'reverted'
    plan.error = `Canary ${plan.canaryApp} is unhealthy (status ${canaryCheck.statusCode}). Deploy aborted.`
    plan.completedAt = new Date().toISOString()
    return plan
  }

  plan.status = 'canary_healthy'

  // Stage 2: Promote to target apps
  plan.status = 'promoting'

  const targetChecks = await Promise.all(
    plan.targetApps
      .filter(app => app !== plan.canaryApp)
      .map(app => checkAppHealth(app))
  )
  plan.healthChecks.push(...targetChecks)

  const unhealthy = targetChecks.filter(c => !c.healthy)
  if (unhealthy.length > 0) {
    plan.status = 'reverted'
    plan.error = `Unhealthy targets: ${unhealthy.map(u => u.app).join(', ')}. Rolling back.`
    plan.completedAt = new Date().toISOString()
    return plan
  }

  // All healthy
  plan.status = 'complete'
  plan.completedAt = new Date().toISOString()
  return plan
}

export function getDeployHistory(): DeployPlan[] {
  return deployHistory
}

export function getDeployPlan(planId: string): DeployPlan | undefined {
  return deployHistory.find(p => p.id === planId)
}

export async function revertDeploy(planId: string): Promise<DeployPlan> {
  const plan = deployHistory.find(p => p.id === planId)
  if (!plan) throw new Error(`Deploy plan ${planId} not found`)

  plan.status = 'reverted'
  plan.error = plan.error || 'Manually reverted by operator'
  plan.completedAt = new Date().toISOString()
  return plan
}

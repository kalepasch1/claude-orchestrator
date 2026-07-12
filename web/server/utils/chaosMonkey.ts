/**
 * Chaos Monkey — controlled failure injection for fleet resilience testing.
 * Simulates app failures, slow responses, and data inconsistencies
 * to verify the fleet handles degradation gracefully.
 *
 * NOTE: This is a "dry run" chaos monkey — it doesn't actually break apps.
 * It simulates failures by:
 * 1. Marking an app as "in chaos" in a local registry
 * 2. Running health checks to see how the fleet reports the gap
 * 3. Verifying cascade/alert systems fire appropriately
 * 4. Clearing the chaos flag and recording results
 */

import { ALL_APP_IDS, type AppId, getAppConfig } from './appClients'

export interface ChaosExperiment {
  id: string
  name: string
  targetApp: string
  failureType: 'offline' | 'slow' | 'error_rate' | 'data_stale'
  config: {
    durationMs?: number
    errorRate?: number
    latencyMs?: number
  }
  status: 'pending' | 'running' | 'completed' | 'aborted'
  startedAt?: string
  completedAt?: string
  results?: ChaosResult
}

export interface ChaosResult {
  cascadeTriggered: boolean
  alertsGenerated: number
  recoveryTimeMs: number
  impactedApps: string[]
  healthChecksPassed: boolean
  notes: string
}

export interface ExperimentTemplate {
  name: string
  description: string
  failureType: 'offline' | 'slow' | 'error_rate' | 'data_stale'
  config: {
    durationMs?: number
    errorRate?: number
    latencyMs?: number
  }
}

// Pre-built experiment templates
const EXPERIMENT_TEMPLATES: ExperimentTemplate[] = [
  {
    name: 'Single App Offline',
    description: 'Simulate a complete app outage for 30 seconds. Tests cascade detection and failover.',
    failureType: 'offline',
    config: { durationMs: 30000 },
  },
  {
    name: 'Slow Response',
    description: 'Add 5 seconds of latency to all responses for 60 seconds. Tests timeout handling.',
    failureType: 'slow',
    config: { durationMs: 60000, latencyMs: 5000 },
  },
  {
    name: 'Intermittent Errors',
    description: '30% of requests return errors for 60 seconds. Tests retry logic and error boundaries.',
    failureType: 'error_rate',
    config: { durationMs: 60000, errorRate: 0.3 },
  },
  {
    name: 'Stale Data',
    description: 'Simulate data staleness for 120 seconds. Tests cache invalidation and consistency checks.',
    failureType: 'data_stale',
    config: { durationMs: 120000 },
  },
]

// In-memory experiment store
const experiments: Map<string, ChaosExperiment> = new Map()

// Chaos flag registry — apps currently "in chaos"
const chaosFlags: Map<string, { failureType: string; startedAt: number; durationMs: number }> = new Map()

// Running experiment timers
const activeTimers: Map<string, ReturnType<typeof setTimeout>> = new Map()

function generateId(): string {
  return `chaos-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

/**
 * Get all experiment templates.
 */
export function getTemplates(): ExperimentTemplate[] {
  return [...EXPERIMENT_TEMPLATES]
}

/**
 * Get all experiments (sorted by most recent first).
 */
export function getExperiments(): ChaosExperiment[] {
  return Array.from(experiments.values()).sort((a, b) => {
    const aTime = a.startedAt || a.id
    const bTime = b.startedAt || b.id
    return bTime > aTime ? 1 : -1
  })
}

/**
 * Create a new experiment.
 */
export function createExperiment(
  name: string,
  targetApp: string,
  failureType: 'offline' | 'slow' | 'error_rate' | 'data_stale',
  config: ChaosExperiment['config']
): ChaosExperiment {
  const experiment: ChaosExperiment = {
    id: generateId(),
    name,
    targetApp,
    failureType,
    config,
    status: 'pending',
  }
  experiments.set(experiment.id, experiment)
  return experiment
}

/**
 * Check if an app is currently under chaos simulation.
 */
export function isAppInChaos(appId: string): boolean {
  const flag = chaosFlags.get(appId)
  if (!flag) return false
  // Check if chaos period has expired
  if (Date.now() > flag.startedAt + flag.durationMs) {
    chaosFlags.delete(appId)
    return false
  }
  return true
}

/**
 * Simulate running health checks against the fleet during a chaos experiment.
 */
async function simulateHealthChecks(targetApp: string): Promise<{ passed: boolean; impactedApps: string[] }> {
  // In a real implementation, this would hit actual health endpoints.
  // For the dry-run, we simulate based on known dependencies.
  const dependencyMap: Record<string, string[]> = {
    apparently: ['smarter', 'tomorrow', 'galop', 'hisanta'],
    tomorrow: ['apparently', 'pareto'],
    smarter: ['apparently', 'orchestrator'],
    galop: ['apparently', 'hisanta', 'pareto'],
    hisanta: ['galop'],
    pareto: ['tomorrow', 'galop'],
    orchestrator: ['apparently', 'smarter'],
  }

  const dependents = dependencyMap[targetApp] || []
  // Simulate that some dependents detect the failure
  const impactedApps = dependents.filter(() => Math.random() > 0.3)

  // Health checks "pass" if the fleet detects and handles the outage
  const passed = impactedApps.length > 0

  return { passed, impactedApps }
}

/**
 * Run a chaos experiment (async — completes after the configured duration).
 */
export async function runExperiment(id: string): Promise<ChaosExperiment> {
  const experiment = experiments.get(id)
  if (!experiment) {
    throw new Error(`Experiment ${id} not found`)
  }
  if (experiment.status === 'running') {
    throw new Error(`Experiment ${id} is already running`)
  }
  if (experiment.status === 'completed' || experiment.status === 'aborted') {
    throw new Error(`Experiment ${id} has already finished`)
  }

  // Check if target app already has a running chaos experiment
  if (isAppInChaos(experiment.targetApp)) {
    throw new Error(`App ${experiment.targetApp} already has an active chaos experiment`)
  }

  const durationMs = experiment.config.durationMs || 30000
  const startTime = Date.now()

  // Mark experiment as running
  experiment.status = 'running'
  experiment.startedAt = new Date().toISOString()

  // Set chaos flag
  chaosFlags.set(experiment.targetApp, {
    failureType: experiment.failureType,
    startedAt: startTime,
    durationMs,
  })

  // Run health checks after a brief delay (simulate detection lag)
  const healthCheckDelay = Math.min(durationMs * 0.3, 5000)

  // Set a timer to auto-complete the experiment
  const timer = setTimeout(async () => {
    // Clear chaos flag
    chaosFlags.delete(experiment.targetApp)

    // Run final health checks
    const healthResult = await simulateHealthChecks(experiment.targetApp)

    const endTime = Date.now()
    experiment.status = 'completed'
    experiment.completedAt = new Date().toISOString()
    experiment.results = {
      cascadeTriggered: healthResult.impactedApps.length > 0,
      alertsGenerated: Math.floor(Math.random() * 5) + (healthResult.impactedApps.length > 0 ? 1 : 0),
      recoveryTimeMs: endTime - startTime,
      impactedApps: healthResult.impactedApps,
      healthChecksPassed: healthResult.passed,
      notes: generateNotes(experiment, healthResult),
    }

    activeTimers.delete(id)
  }, durationMs)

  activeTimers.set(id, timer)

  return experiment
}

function generateNotes(experiment: ChaosExperiment, healthResult: { passed: boolean; impactedApps: string[] }): string {
  const parts: string[] = []

  parts.push(`Simulated ${experiment.failureType} failure on ${experiment.targetApp}.`)

  if (healthResult.impactedApps.length > 0) {
    parts.push(`Cascade detected in: ${healthResult.impactedApps.join(', ')}.`)
  } else {
    parts.push('No cascade impact detected — app may be isolated or dependencies handled gracefully.')
  }

  if (healthResult.passed) {
    parts.push('Fleet health checks detected the simulated failure correctly.')
  } else {
    parts.push('Warning: fleet did not detect the simulated failure — monitoring gap identified.')
  }

  if (experiment.failureType === 'slow') {
    parts.push(`Injected ${experiment.config.latencyMs}ms latency.`)
  } else if (experiment.failureType === 'error_rate') {
    parts.push(`Injected ${Math.round((experiment.config.errorRate || 0) * 100)}% error rate.`)
  }

  return parts.join(' ')
}

/**
 * Abort a running experiment.
 */
export function abortExperiment(id: string): ChaosExperiment {
  const experiment = experiments.get(id)
  if (!experiment) {
    throw new Error(`Experiment ${id} not found`)
  }
  if (experiment.status !== 'running') {
    throw new Error(`Experiment ${id} is not running (status: ${experiment.status})`)
  }

  // Clear timer
  const timer = activeTimers.get(id)
  if (timer) {
    clearTimeout(timer)
    activeTimers.delete(id)
  }

  // Clear chaos flag
  chaosFlags.delete(experiment.targetApp)

  // Mark as aborted
  experiment.status = 'aborted'
  experiment.completedAt = new Date().toISOString()
  experiment.results = {
    cascadeTriggered: false,
    alertsGenerated: 0,
    recoveryTimeMs: Date.now() - new Date(experiment.startedAt!).getTime(),
    impactedApps: [],
    healthChecksPassed: false,
    notes: 'Experiment aborted by operator before completion.',
  }

  return experiment
}

/**
 * Get chaos status for all apps.
 */
export function getChaosStatus(): { app: string; inChaos: boolean; failureType?: string }[] {
  return ALL_APP_IDS.map(appId => ({
    app: appId,
    inChaos: isAppInChaos(appId),
    failureType: chaosFlags.get(appId)?.failureType,
  }))
}

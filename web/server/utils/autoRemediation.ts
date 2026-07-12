/**
 * Auto-Remediation Playbooks — predefined response plans for known anomaly patterns.
 * When Anomaly Radar fires an alert matching a playbook trigger, the playbook
 * auto-executes (or queues for approval based on severity).
 */
import type { AnomalyAlert } from './anomalyRadar'

export interface PlaybookStep {
  type: 'fleet_execute' | 'toggle_feature' | 'notify' | 'revert_deploy' | 'scale' | 'custom'
  app?: string
  action?: string
  payload?: any
  description: string
}

export interface Playbook {
  id: string
  name: string
  description: string
  trigger: {
    metricPattern: string
    severityMin: 'warning' | 'critical'
    appPattern?: string
  }
  steps: PlaybookStep[]
  requiresApproval: boolean
  cooldownMs: number
  enabled: boolean
  lastExecutedAt?: string
  executionCount: number
}

export interface PlaybookExecution {
  id: string
  playbookId: string
  playbookName: string
  triggeredBy: string
  triggerAlert?: AnomalyAlert
  status: 'pending_approval' | 'executing' | 'completed' | 'failed' | 'aborted'
  steps: { step: PlaybookStep; status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'; result?: any; error?: string }[]
  startedAt: string
  completedAt?: string
}

// In-memory state
let playbooks: Playbook[] = []
let executions: PlaybookExecution[] = []
let initialized = false

function ensureDefaults() {
  if (initialized) return
  initialized = true
  playbooks = [
    {
      id: 'pb-error-spike',
      name: 'Error Spike Response',
      description: 'When error rate spikes, toggle the last-deployed feature flag off and notify',
      trigger: { metricPattern: 'error_rate', severityMin: 'critical' },
      steps: [
        { type: 'toggle_feature', description: 'Disable last deployed feature flag' },
        { type: 'notify', description: 'Alert ops channel' },
      ],
      requiresApproval: false,
      cooldownMs: 300000,
      enabled: true,
      executionCount: 0,
    },
    {
      id: 'pb-high-rejection',
      name: 'High Rejection Rate',
      description: 'When approval rejection rate is anomalously high, pause auto-execution and escalate',
      trigger: { metricPattern: 'rejection_rate', severityMin: 'warning' },
      steps: [
        { type: 'custom', action: 'pause_auto_execute', description: 'Pause all auto-execute policies' },
        { type: 'notify', description: 'Escalate to senior ops' },
      ],
      requiresApproval: true,
      cooldownMs: 900000,
      enabled: true,
      executionCount: 0,
    },
    {
      id: 'pb-app-down',
      name: 'App Health Failure',
      description: 'When an app fails health checks, check deploy history and offer revert',
      trigger: { metricPattern: 'health_check', severityMin: 'critical' },
      steps: [
        { type: 'revert_deploy', description: 'Revert to last known good deploy' },
        { type: 'notify', description: 'Alert ops with incident details' },
      ],
      requiresApproval: true,
      cooldownMs: 600000,
      enabled: true,
      executionCount: 0,
    },
    {
      id: 'pb-volume-drop',
      name: 'Traffic Volume Drop',
      description: 'When event volume drops significantly, run health checks and create incident',
      trigger: { metricPattern: 'event_volume', severityMin: 'warning' },
      steps: [
        { type: 'custom', action: 'health_check_all', description: 'Run health checks on all apps' },
        { type: 'notify', description: 'Create incident report' },
      ],
      requiresApproval: false,
      cooldownMs: 600000,
      enabled: true,
      executionCount: 0,
    },
  ]
}

function makeExecutionId(): string {
  return `exec-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

/**
 * Find the first enabled playbook whose trigger matches the given anomaly alert.
 */
export function matchPlaybook(alert: AnomalyAlert): Playbook | null {
  ensureDefaults()

  const severityRank: Record<string, number> = { info: 0, warning: 1, critical: 2 }

  for (const pb of playbooks) {
    if (!pb.enabled) continue

    // Check metric pattern
    try {
      const metricRegex = new RegExp(pb.trigger.metricPattern, 'i')
      const metricStr = alert.metric.toLowerCase().replace(/\s+/g, '_')
      if (!metricRegex.test(metricStr)) continue
    } catch {
      continue
    }

    // Check severity minimum
    if (severityRank[alert.severity] < severityRank[pb.trigger.severityMin]) continue

    // Check app pattern
    if (pb.trigger.appPattern && pb.trigger.appPattern !== '*') {
      try {
        const appRegex = new RegExp(pb.trigger.appPattern, 'i')
        if (!appRegex.test(alert.app)) continue
      } catch {
        continue
      }
    }

    // Check cooldown
    if (pb.lastExecutedAt) {
      const elapsed = Date.now() - new Date(pb.lastExecutedAt).getTime()
      if (elapsed < pb.cooldownMs) continue
    }

    return pb
  }

  return null
}

/**
 * Execute a playbook. Steps run sequentially; each step is simulated
 * (actual fleet integration would call real APIs).
 */
export async function executePlaybook(playbookId: string, triggeredBy: string, triggerAlert?: AnomalyAlert): Promise<PlaybookExecution> {
  ensureDefaults()

  const pb = playbooks.find(p => p.id === playbookId)
  if (!pb) {
    throw new Error(`Playbook not found: ${playbookId}`)
  }

  const execution: PlaybookExecution = {
    id: makeExecutionId(),
    playbookId: pb.id,
    playbookName: pb.name,
    triggeredBy,
    triggerAlert,
    status: pb.requiresApproval ? 'pending_approval' : 'executing',
    steps: pb.steps.map(step => ({ step, status: 'pending' as const })),
    startedAt: new Date().toISOString(),
  }

  executions.unshift(execution)

  // If requires approval, stop here -- wait for approveExecution()
  if (pb.requiresApproval) {
    return execution
  }

  // Execute immediately
  await runExecutionSteps(execution, pb)
  return execution
}

async function runExecutionSteps(execution: PlaybookExecution, pb: Playbook): Promise<void> {
  execution.status = 'executing'

  for (const stepEntry of execution.steps) {
    if (execution.status === 'aborted') {
      stepEntry.status = 'skipped'
      continue
    }

    stepEntry.status = 'running'

    try {
      // Simulate step execution with a brief delay
      await new Promise(resolve => setTimeout(resolve, 50))

      switch (stepEntry.step.type) {
        case 'toggle_feature':
          stepEntry.result = { action: 'feature_toggled', flag: 'last_deployed', state: 'disabled' }
          break
        case 'notify':
          stepEntry.result = { action: 'notification_sent', channel: 'ops', message: stepEntry.step.description }
          break
        case 'revert_deploy':
          stepEntry.result = { action: 'deploy_reverted', target: 'last_known_good' }
          break
        case 'scale':
          stepEntry.result = { action: 'scaled', direction: stepEntry.step.payload?.direction || 'up' }
          break
        case 'fleet_execute':
          stepEntry.result = { action: 'fleet_command_sent', app: stepEntry.step.app, command: stepEntry.step.action }
          break
        case 'custom':
          stepEntry.result = { action: stepEntry.step.action || 'custom_executed', description: stepEntry.step.description }
          break
      }

      stepEntry.status = 'completed'
    } catch (e: any) {
      stepEntry.status = 'failed'
      stepEntry.error = e.message || 'Step execution failed'
      execution.status = 'failed'
      execution.completedAt = new Date().toISOString()
      return
    }
  }

  execution.status = 'completed'
  execution.completedAt = new Date().toISOString()

  // Update playbook stats
  pb.lastExecutedAt = execution.startedAt
  pb.executionCount++
}

/**
 * Approve a pending execution and start running its steps.
 */
export async function approveExecution(executionId: string): Promise<PlaybookExecution> {
  const execution = executions.find(e => e.id === executionId)
  if (!execution) {
    throw new Error(`Execution not found: ${executionId}`)
  }
  if (execution.status !== 'pending_approval') {
    throw new Error(`Execution is not pending approval (status: ${execution.status})`)
  }

  const pb = playbooks.find(p => p.id === execution.playbookId)
  if (!pb) {
    throw new Error(`Playbook not found: ${execution.playbookId}`)
  }

  await runExecutionSteps(execution, pb)
  return execution
}

/**
 * Abort a pending or executing execution.
 */
export function abortExecution(executionId: string): PlaybookExecution {
  const execution = executions.find(e => e.id === executionId)
  if (!execution) {
    throw new Error(`Execution not found: ${executionId}`)
  }

  execution.status = 'aborted'
  execution.completedAt = new Date().toISOString()

  for (const step of execution.steps) {
    if (step.status === 'pending' || step.status === 'running') {
      step.status = 'skipped'
    }
  }

  return execution
}

/**
 * Get all playbooks.
 */
export function getPlaybooks(): Playbook[] {
  ensureDefaults()
  return [...playbooks]
}

/**
 * Get execution history.
 */
export function getExecutionHistory(): PlaybookExecution[] {
  return [...executions]
}

/**
 * Update a playbook's settings.
 */
export function updatePlaybook(id: string, updates: Partial<Pick<Playbook, 'enabled' | 'name' | 'description' | 'requiresApproval' | 'cooldownMs' | 'steps' | 'trigger'>>): Playbook {
  ensureDefaults()

  const pb = playbooks.find(p => p.id === id)
  if (!pb) {
    throw new Error(`Playbook not found: ${id}`)
  }

  if (updates.enabled !== undefined) pb.enabled = updates.enabled
  if (updates.name !== undefined) pb.name = updates.name
  if (updates.description !== undefined) pb.description = updates.description
  if (updates.requiresApproval !== undefined) pb.requiresApproval = updates.requiresApproval
  if (updates.cooldownMs !== undefined) pb.cooldownMs = updates.cooldownMs
  if (updates.steps !== undefined) pb.steps = updates.steps
  if (updates.trigger !== undefined) pb.trigger = { ...pb.trigger, ...updates.trigger }

  return { ...pb }
}

/**
 * Create a new playbook.
 */
export function createPlaybook(input: Omit<Playbook, 'id' | 'executionCount' | 'lastExecutedAt'>): Playbook {
  ensureDefaults()

  const pb: Playbook = {
    ...input,
    id: `pb-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    executionCount: 0,
  }

  playbooks.push(pb)
  return { ...pb }
}

/**
 * Process an anomaly alert: check for matching playbook and auto-execute or queue.
 */
export async function processAnomalyAlert(alert: AnomalyAlert): Promise<PlaybookExecution | null> {
  const pb = matchPlaybook(alert)
  if (!pb) return null

  return executePlaybook(pb.id, alert.id, alert)
}

/**
 * Admin Action Replay — records admin sessions as replayable scripts.
 * Captures NL Admin queries, proxy API calls, fleet executions, and policy decisions
 * as an ordered sequence that can be replayed, shared, or scheduled.
 */

export interface ReplayAction {
  seq: number
  type: 'nl_query' | 'proxy_query' | 'fleet_execute' | 'policy_decision' | 'approval' | 'playbook_trigger'
  timestamp: string
  input: any
  output?: any
  app?: string
  duration_ms?: number
}

export interface Recording {
  id: string
  name: string
  description: string
  createdBy: string
  createdAt: string
  updatedAt: string
  actions: ReplayAction[]
  tags: string[]
  replayCount: number
  lastReplayedAt?: string
  status: 'recording' | 'saved' | 'archived'
}

export interface ReplayResult {
  recordingId: string
  replayedAt: string
  actions: {
    seq: number
    originalOutput: any
    replayOutput: any
    matched: boolean
    duration_ms: number
    error?: string
  }[]
  overallMatch: number
  duration_ms: number
}

// In-memory state
const recordings: Map<string, Recording> = new Map()
let activeRecordingId: string | null = null

function generateId(): string {
  return 'rec-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8)
}

// ---------- Recording lifecycle ----------

export function startRecording(name: string, description: string, createdBy: string): Recording {
  if (activeRecordingId) {
    // Auto-stop any existing active recording
    stopRecording(activeRecordingId)
  }

  const recording: Recording = {
    id: generateId(),
    name,
    description,
    createdBy,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    actions: [],
    tags: [],
    replayCount: 0,
    status: 'recording',
  }

  recordings.set(recording.id, recording)
  activeRecordingId = recording.id
  return recording
}

export function addAction(recordingId: string, action: Omit<ReplayAction, 'seq'>): void {
  const recording = recordings.get(recordingId)
  if (!recording || recording.status !== 'recording') return

  const seq = recording.actions.length + 1
  recording.actions.push({ ...action, seq })
  recording.updatedAt = new Date().toISOString()
}

export function stopRecording(recordingId: string): Recording | null {
  const recording = recordings.get(recordingId)
  if (!recording) return null

  recording.status = 'saved'
  recording.updatedAt = new Date().toISOString()
  if (activeRecordingId === recordingId) {
    activeRecordingId = null
  }
  return recording
}

export function getActiveRecording(): Recording | null {
  if (!activeRecordingId) return null
  return recordings.get(activeRecordingId) || null
}

// ---------- Replay ----------

export async function replayRecording(
  recordingId: string,
  options?: { dryRun?: boolean; skipExecutes?: boolean }
): Promise<ReplayResult> {
  const recording = recordings.get(recordingId)
  if (!recording) {
    throw new Error(`Recording ${recordingId} not found`)
  }

  const dryRun = options?.dryRun ?? false
  const skipExecutes = options?.skipExecutes ?? false
  const replayStart = Date.now()
  const replayActions: ReplayResult['actions'] = []

  for (const action of recording.actions) {
    const actionStart = Date.now()
    let replayOutput: any = null
    let error: string | undefined
    let matched = false

    try {
      switch (action.type) {
        case 'nl_query': {
          if (dryRun) {
            replayOutput = { dryRun: true, wouldPost: '/api/admin/nl-query', input: action.input }
          } else {
            const resp = await $fetch('/api/admin/nl-query', {
              method: 'POST',
              body: action.input,
            }).catch((e: any) => ({ error: e.message }))
            replayOutput = resp
          }
          break
        }

        case 'proxy_query': {
          if (dryRun) {
            replayOutput = { dryRun: true, wouldPost: `/api/proxy/${action.app}/query`, input: action.input }
          } else {
            const resp = await $fetch(`/api/proxy/${action.app}/query`, {
              method: 'POST',
              body: action.input,
            }).catch((e: any) => ({ error: e.message }))
            replayOutput = resp
          }
          break
        }

        case 'fleet_execute': {
          if (dryRun || skipExecutes) {
            replayOutput = { skipped: true, reason: dryRun ? 'dry_run' : 'skip_executes', input: action.input }
          } else {
            const resp = await $fetch(`/api/proxy/${action.app}/execute`, {
              method: 'POST',
              body: action.input,
            }).catch((e: any) => ({ error: e.message }))
            replayOutput = resp
          }
          break
        }

        case 'policy_decision': {
          replayOutput = { type: 'policy_comparison', input: action.input, note: 'Policy engine comparison' }
          break
        }

        case 'approval': {
          if (dryRun) {
            replayOutput = { dryRun: true, wouldPost: '/api/approvals/decide', input: action.input }
          } else {
            const resp = await $fetch('/api/approvals/decide', {
              method: 'POST',
              body: action.input,
            }).catch((e: any) => ({ error: e.message }))
            replayOutput = resp
          }
          break
        }

        case 'playbook_trigger': {
          if (dryRun) {
            replayOutput = { dryRun: true, wouldPost: '/api/admin/playbooks/execute', input: action.input }
          } else {
            const resp = await $fetch('/api/admin/playbooks/execute', {
              method: 'POST',
              body: action.input,
            }).catch((e: any) => ({ error: e.message }))
            replayOutput = resp
          }
          break
        }
      }

      // Simple output comparison — check for structural similarity
      matched = compareOutputs(action.output, replayOutput)
    } catch (e: any) {
      error = e.message || 'Unknown replay error'
      matched = false
    }

    replayActions.push({
      seq: action.seq,
      originalOutput: action.output,
      replayOutput,
      matched,
      duration_ms: Date.now() - actionStart,
      error,
    })
  }

  // Update recording stats
  recording.replayCount++
  recording.lastReplayedAt = new Date().toISOString()

  const matchCount = replayActions.filter(a => a.matched).length
  const overallMatch = replayActions.length > 0 ? Math.round((matchCount / replayActions.length) * 100) : 100

  return {
    recordingId,
    replayedAt: new Date().toISOString(),
    actions: replayActions,
    overallMatch,
    duration_ms: Date.now() - replayStart,
  }
}

function compareOutputs(original: any, replay: any): boolean {
  if (original === undefined || original === null) return true // No original to compare against
  if (replay?.dryRun || replay?.skipped) return true // Can't compare dry runs
  if (replay?.error) return false

  try {
    // Check if both have same top-level keys
    if (typeof original === 'object' && typeof replay === 'object') {
      const origKeys = Object.keys(original).sort()
      const replayKeys = Object.keys(replay).sort()
      // If they share at least 50% of keys, consider it a match
      const shared = origKeys.filter(k => replayKeys.includes(k))
      return shared.length >= origKeys.length * 0.5
    }
    return String(original) === String(replay)
  } catch {
    return false
  }
}

// ---------- Management ----------

export function getRecordings(tags?: string[]): Recording[] {
  const all = Array.from(recordings.values())
  if (!tags || tags.length === 0) return all
  return all.filter(r => tags.some(t => r.tags.includes(t)))
}

export function getRecording(id: string): Recording | null {
  return recordings.get(id) || null
}

export function deleteRecording(id: string): void {
  if (activeRecordingId === id) {
    activeRecordingId = null
  }
  recordings.delete(id)
}

export function tagRecording(id: string, tags: string[]): void {
  const recording = recordings.get(id)
  if (!recording) return
  recording.tags = [...new Set([...recording.tags, ...tags])]
  recording.updatedAt = new Date().toISOString()
}

export function cloneRecording(id: string, newName: string): Recording | null {
  const original = recordings.get(id)
  if (!original) return null

  const clone: Recording = {
    ...original,
    id: generateId(),
    name: newName,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    actions: JSON.parse(JSON.stringify(original.actions)),
    tags: [...original.tags],
    replayCount: 0,
    lastReplayedAt: undefined,
    status: 'saved',
  }

  recordings.set(clone.id, clone)
  return clone
}

// ---------- Templates ----------

export function generateIncidentResponseTemplate(): Recording {
  const id = generateId()
  const template: Recording = {
    id,
    name: 'Incident Response',
    description: 'Standard incident response: check health, scan anomalies, review predictions, run playbook',
    createdBy: 'system',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    tags: ['incident-response', 'template'],
    replayCount: 0,
    status: 'saved',
    actions: [
      { seq: 1, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Show fleet health status for all apps' } },
      { seq: 2, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Scan for anomalies across all apps in the last hour' } },
      { seq: 3, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Show predictive incident analysis' } },
      { seq: 4, type: 'playbook_trigger', timestamp: new Date().toISOString(), input: { playbookId: 'pb-error-spike', reason: 'Incident response template' } },
    ],
  }
  recordings.set(id, template)
  return template
}

export function generateAuditTemplate(): Recording {
  const id = generateId()
  const template: Recording = {
    id,
    name: 'Compliance Audit',
    description: 'Standard audit: generate regulatory snapshot, review compliance graph, export report',
    createdBy: 'system',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    tags: ['audit', 'compliance', 'template'],
    replayCount: 0,
    status: 'saved',
    actions: [
      { seq: 1, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Generate regulatory compliance snapshot for all apps' } },
      { seq: 2, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Show compliance dependency graph' } },
      { seq: 3, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Export compliance report' } },
    ],
  }
  recordings.set(id, template)
  return template
}

export function generateOnboardingTemplate(): Recording {
  const id = generateId()
  const template: Recording = {
    id,
    name: 'User Onboarding Verification',
    description: 'Verify new user setup: cross-app search, check workspace, verify permissions',
    createdBy: 'system',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    tags: ['onboarding', 'template'],
    replayCount: 0,
    status: 'saved',
    actions: [
      { seq: 1, type: 'proxy_query', timestamp: new Date().toISOString(), input: { query: 'Search for user across all apps' }, app: 'orchestrator' },
      { seq: 2, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Check workspace configuration for new user' } },
      { seq: 3, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Verify user permissions across all apps' } },
    ],
  }
  recordings.set(id, template)
  return template
}

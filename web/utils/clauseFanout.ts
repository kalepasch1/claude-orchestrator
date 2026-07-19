/**
 * clauseFanout.ts — Clause fan-out regeneration engine.
 *
 * When a shared legal clause is edited, this module enumerates all
 * consuming documents and produces regeneration tasks for each.
 * Fail-soft: individual doc failures are bounced, others continue.
 */

export interface Clause {
  clauseId: string
  version: number
  text: string
  updatedAt: number
}

export interface ConsumingDoc {
  docId: string
  docType: string
  appId: string
  clauseRefs: string[]  // clause IDs used in this doc
}

export interface RegenerationTask {
  taskId: string
  docId: string
  clauseId: string
  newClauseText: string
  status: 'pending' | 'success' | 'failed' | 'bounced'
  error?: string
}

export interface BatchApproval {
  batchId: string
  clauseId: string
  tasks: RegenerationTask[]
  totalDocs: number
  successCount: number
  failedCount: number
  bouncedCount: number
  ready: boolean
}

// ── In-memory doc registry ───────────────────────────────────────────────────

const _docRegistry = new Map<string, ConsumingDoc>()

export function registerDoc(doc: ConsumingDoc): void {
  _docRegistry.set(doc.docId, { ...doc })
}

export function clearDocRegistry(): void {
  _docRegistry.clear()
}

// ── Core ─────────────────────────────────────────────────────────────────────

export function findConsumers(clauseId: string): ConsumingDoc[] {
  const consumers: ConsumingDoc[] = []
  for (const doc of _docRegistry.values()) {
    if (doc.clauseRefs.includes(clauseId)) consumers.push(doc)
  }
  return consumers
}

export function createRegenerationTasks(clause: Clause, consumers: ConsumingDoc[]): RegenerationTask[] {
  return consumers.map((doc) => ({
    taskId: `regen_${clause.clauseId}_${doc.docId}_${clause.version}`,
    docId: doc.docId,
    clauseId: clause.clauseId,
    newClauseText: clause.text,
    status: 'pending' as const,
  }))
}

/**
 * Execute regeneration with fail-soft behavior.
 * Individual failures are bounced; others continue.
 */
export function executeRegeneration(
  tasks: RegenerationTask[],
  regenerateFn: (task: RegenerationTask) => boolean,
): RegenerationTask[] {
  return tasks.map(task => {
    try {
      const success = regenerateFn(task)
      return { ...task, status: success ? 'success' as const : 'failed' as const }
    } catch (e: any) {
      return { ...task, status: 'bounced' as const, error: e?.message ?? 'Unknown error' }
    }
  })
}

export function createBatchApproval(clauseId: string, tasks: RegenerationTask[]): BatchApproval {
  const successCount = tasks.filter(t => t.status === 'success').length
  const failedCount = tasks.filter(t => t.status === 'failed').length
  const bouncedCount = tasks.filter(t => t.status === 'bounced').length

  return {
    batchId: `batch_${clauseId}_${Date.now().toString(36)}`,
    clauseId,
    tasks,
    totalDocs: tasks.length,
    successCount,
    failedCount,
    bouncedCount,
    ready: successCount > 0 && failedCount === 0,
  }
}

/**
 * Full fan-out pipeline: clause edit → find consumers → regenerate → batch approval.
 */
export function fanOutClauseEdit(
  clause: Clause,
  regenerateFn: (task: RegenerationTask) => boolean = () => true,
): BatchApproval {
  const consumers = findConsumers(clause.clauseId)
  const tasks = createRegenerationTasks(clause, consumers)
  const executed = executeRegeneration(tasks, regenerateFn)
  return createBatchApproval(clause.clauseId, executed)
}

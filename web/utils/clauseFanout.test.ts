import { describe, it, expect, beforeEach } from 'vitest'
import {
  registerDoc, clearDocRegistry, findConsumers,
  createRegenerationTasks, executeRegeneration,
  createBatchApproval, fanOutClauseEdit,
  type Clause, type ConsumingDoc,
} from './clauseFanout'

describe('clauseFanout', () => {
  beforeEach(() => clearDocRegistry())

  const clause: Clause = { clauseId: 'cl_1', version: 2, text: 'Updated clause text', updatedAt: 1000 }

  it('findConsumers returns docs referencing the clause', () => {
    registerDoc({ docId: 'd1', docType: 'tos', appId: 'app1', clauseRefs: ['cl_1', 'cl_2'] })
    registerDoc({ docId: 'd2', docType: 'privacy', appId: 'app1', clauseRefs: ['cl_3'] })
    registerDoc({ docId: 'd3', docType: 'tos', appId: 'app2', clauseRefs: ['cl_1'] })

    const consumers = findConsumers('cl_1')
    expect(consumers).toHaveLength(2)
    expect(consumers.map(c => c.docId).sort()).toEqual(['d1', 'd3'])
  })

  it('createRegenerationTasks creates one task per consumer', () => {
    const consumers: ConsumingDoc[] = [
      { docId: 'd1', docType: 'tos', appId: 'app1', clauseRefs: ['cl_1'] },
      { docId: 'd2', docType: 'pp', appId: 'app2', clauseRefs: ['cl_1'] },
    ]
    const tasks = createRegenerationTasks(clause, consumers)
    expect(tasks).toHaveLength(2)
    expect(tasks.every(t => t.status === 'pending')).toBe(true)
    expect(tasks.every(t => t.newClauseText === 'Updated clause text')).toBe(true)
  })

  it('executeRegeneration handles success', () => {
    const tasks = createRegenerationTasks(clause, [
      { docId: 'd1', docType: 'tos', appId: 'app1', clauseRefs: ['cl_1'] },
    ])
    const results = executeRegeneration(tasks, () => true)
    expect(results[0].status).toBe('success')
  })

  it('executeRegeneration bounces on thrown error (fail-soft)', () => {
    const tasks = createRegenerationTasks(clause, [
      { docId: 'd1', docType: 'tos', appId: 'app1', clauseRefs: ['cl_1'] },
    ])
    const results = executeRegeneration(tasks, () => { throw new Error('doc corrupt') })
    expect(results[0].status).toBe('bounced')
    expect(results[0].error).toBe('doc corrupt')
  })

  it('executeRegeneration marks false returns as failed', () => {
    const tasks = createRegenerationTasks(clause, [
      { docId: 'd1', docType: 'tos', appId: 'app1', clauseRefs: ['cl_1'] },
    ])
    const results = executeRegeneration(tasks, () => false)
    expect(results[0].status).toBe('failed')
  })

  it('batch approval is ready when all succeed', () => {
    const tasks = [
      { taskId: 't1', docId: 'd1', clauseId: 'cl_1', newClauseText: 'x', status: 'success' as const },
      { taskId: 't2', docId: 'd2', clauseId: 'cl_1', newClauseText: 'x', status: 'success' as const },
    ]
    const batch = createBatchApproval('cl_1', tasks)
    expect(batch.ready).toBe(true)
    expect(batch.successCount).toBe(2)
  })

  it('batch approval not ready when any failed', () => {
    const tasks = [
      { taskId: 't1', docId: 'd1', clauseId: 'cl_1', newClauseText: 'x', status: 'success' as const },
      { taskId: 't2', docId: 'd2', clauseId: 'cl_1', newClauseText: 'x', status: 'failed' as const },
    ]
    const batch = createBatchApproval('cl_1', tasks)
    expect(batch.ready).toBe(false)
  })

  it('full fanOutClauseEdit pipeline', () => {
    registerDoc({ docId: 'd1', docType: 'tos', appId: 'app1', clauseRefs: ['cl_1'] })
    registerDoc({ docId: 'd2', docType: 'pp', appId: 'app2', clauseRefs: ['cl_1'] })
    registerDoc({ docId: 'd3', docType: 'nda', appId: 'app3', clauseRefs: ['cl_other'] })

    const batch = fanOutClauseEdit(clause)
    expect(batch.totalDocs).toBe(2)
    expect(batch.successCount).toBe(2)
    expect(batch.ready).toBe(true)
  })

  it('empty consumers → empty batch', () => {
    const batch = fanOutClauseEdit(clause)
    expect(batch.totalDocs).toBe(0)
    expect(batch.ready).toBe(false)  // 0 success
  })

  // Mixed results
  it('mixed success/bounce → not ready but has results', () => {
    registerDoc({ docId: 'd1', docType: 'tos', appId: 'app1', clauseRefs: ['cl_1'] })
    registerDoc({ docId: 'd2', docType: 'pp', appId: 'app2', clauseRefs: ['cl_1'] })

    let callCount = 0
    const batch = fanOutClauseEdit(clause, () => {
      callCount++
      if (callCount === 2) throw new Error('boom')
      return true
    })
    expect(batch.successCount).toBe(1)
    expect(batch.bouncedCount).toBe(1)
  })
})

import { describe, it, expect, vi } from 'vitest'
import { processBatch } from '../legal-batch'

describe('legal batch processing', () => {
  it('processes multiple items successfully', async () => {
    const items = [
      { id: '1', action: 'create_draft', values: { template_key: 'msa' } },
      { id: '2', action: 'review', values: { contract_id: 'c1' } }
    ]

    const handler = vi.fn(async (_, item) => ({ action: item.action, processed: true }))
    const results = await processBatch({} as any, items, handler)

    expect(results).toHaveLength(2)
    expect(results[0].status).toBe('success')
    expect(results[0].item_id).toBe('1')
    expect(results[1].status).toBe('success')
    expect(results[1].item_id).toBe('2')
    expect(handler).toHaveBeenCalledTimes(2)
  })

  it('captures errors without stopping batch', async () => {
    const items = [
      { id: '1', action: 'valid' },
      { id: '2', action: 'invalid' },
      { id: '3', action: 'valid' }
    ]

    const handler = vi.fn(async (_, item) => {
      if (item.action === 'invalid') throw new Error('test error')
      return { ok: true }
    })

    const results = await processBatch({} as any, items, handler)

    expect(results).toHaveLength(3)
    expect(results[0].status).toBe('success')
    expect(results[1].status).toBe('error')
    expect(results[1].error).toBe('test error')
    expect(results[2].status).toBe('success')
  })

  it('limits batch to 100 items', async () => {
    const items = Array.from({ length: 150 }, (_, i) => ({
      id: String(i),
      action: 'test'
    }))

    const handler = vi.fn(async () => ({ ok: true }))
    const results = await processBatch({} as any, items, handler)

    expect(results).toHaveLength(100)
    expect(handler).toHaveBeenCalledTimes(100)
  })

  it('includes item_id only when provided', async () => {
    const items = [
      { action: 'test' },
      { id: 'explicit', action: 'test' }
    ]

    const handler = vi.fn(async () => ({ ok: true }))
    const results = await processBatch({} as any, items, handler)

    expect(results[0].item_id).toBeUndefined()
    expect(results[1].item_id).toBe('explicit')
  })
})

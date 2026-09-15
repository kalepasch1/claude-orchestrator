import type { H3Event } from 'h3'

interface BatchItem {
  id?: string
  action: string
  values?: Record<string, any>
}

interface BatchResult {
  item_id?: string
  action: string
  status: 'success' | 'error'
  result?: any
  error?: string
}

export async function processBatch(
  event: H3Event,
  items: BatchItem[],
  handler: (event: H3Event, item: BatchItem) => Promise<any>
): Promise<BatchResult[]> {
  const results: BatchResult[] = []
  const validated = items.slice(0, 100)

  for (const item of validated) {
    try {
      const result = await handler(event, item)
      results.push({
        item_id: item.id || undefined,
        action: item.action,
        status: 'success',
        result
      })
    } catch (error: any) {
      results.push({
        item_id: item.id || undefined,
        action: item.action,
        status: 'error',
        error: String(error?.message || error).slice(0, 300)
      })
    }
  }

  return results
}

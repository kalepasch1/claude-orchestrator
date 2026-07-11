/**
 * Temporal Admin — tracks fleet actions as an undo chain.
 * Every execute response can include an undoToken. This module stores them,
 * enforces a configurable undo window (default 15 min), and chains multi-step undos.
 */

export interface ActionReceipt {
  id: string
  app: string
  action: string
  domain: string
  payload: any
  undoToken?: string
  undoAction?: string
  executedAt: string
  undoDeadline: string
  undoneAt?: string
  undoneBy?: string
  chainId?: string
}

const UNDO_WINDOW_MS = parseInt(process.env.ORCH_UNDO_WINDOW_MS || '900000', 10) // 15 min

const receipts: ActionReceipt[] = []

function makeId(): string {
  return `rcpt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function recordAction(
  app: string,
  action: string,
  domain: string,
  payload: any,
  undoToken?: string,
  undoAction?: string,
  chainId?: string,
): ActionReceipt {
  const now = new Date()
  const receipt: ActionReceipt = {
    id: makeId(),
    app,
    action,
    domain,
    payload,
    undoToken,
    undoAction,
    executedAt: now.toISOString(),
    undoDeadline: new Date(now.getTime() + UNDO_WINDOW_MS).toISOString(),
    chainId,
  }
  receipts.unshift(receipt)
  // Cap at 500 entries
  if (receipts.length > 500) receipts.length = 500
  return receipt
}

export function isWithinUndoWindow(receipt: ActionReceipt): boolean {
  if (receipt.undoneAt) return false
  if (!receipt.undoToken) return false
  return new Date(receipt.undoDeadline).getTime() > Date.now()
}

export function getUndoableActions(): ActionReceipt[] {
  return receipts.filter(isWithinUndoWindow)
}

export function getActionHistory(limit = 50): ActionReceipt[] {
  return receipts.slice(0, limit)
}

export async function undoAction(receiptId: string, undoneBy: string): Promise<{ success: boolean; error?: string }> {
  const receipt = receipts.find(r => r.id === receiptId)
  if (!receipt) return { success: false, error: 'Receipt not found' }
  if (!isWithinUndoWindow(receipt)) return { success: false, error: 'Undo window expired or action already undone' }
  if (!receipt.undoToken || !receipt.undoAction) return { success: false, error: 'No undo token available for this action' }

  try {
    const appClients = await import('./appClients').catch(() => null)
    if (appClients) {
      const client = (appClients as any).getAppClient?.(receipt.app)
      if (client?.executeUrl) {
        await $fetch(client.executeUrl, {
          method: 'POST',
          body: {
            action: receipt.undoAction,
            domain: receipt.domain,
            undoToken: receipt.undoToken,
            payload: receipt.payload,
          },
        }).catch(() => null)
      }
    }

    receipt.undoneAt = new Date().toISOString()
    receipt.undoneBy = undoneBy
    return { success: true }
  } catch (err: any) {
    return { success: false, error: err?.message || 'Undo execution failed' }
  }
}

export async function undoChain(chainId: string, undoneBy: string): Promise<{ undone: number; errors: string[] }> {
  const chain = receipts
    .filter(r => r.chainId === chainId && isWithinUndoWindow(r))
    .sort((a, b) => new Date(b.executedAt).getTime() - new Date(a.executedAt).getTime())

  let undone = 0
  const errors: string[] = []

  for (const receipt of chain) {
    const result = await undoAction(receipt.id, undoneBy)
    if (result.success) {
      undone++
    } else if (result.error) {
      errors.push(`${receipt.id}: ${result.error}`)
    }
  }

  return { undone, errors }
}

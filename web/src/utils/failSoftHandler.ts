/**
 * failSoftHandler.ts — Upgraded fail-soft error handling.
 * Returns sensible defaults instead of throwing on errors.
 */
export interface FailSoftResult<T> {
  value: T
  error: string | null
  fellBack: boolean
}

export function failSoft<T>(fn: () => T, fallback: T): FailSoftResult<T> {
  try {
    const value = fn()
    return { value, error: null, fellBack: false }
  } catch (e: any) {
    return { value: fallback, error: e?.message ?? 'Unknown error', fellBack: true }
  }
}

export async function failSoftAsync<T>(fn: () => Promise<T>, fallback: T): Promise<FailSoftResult<T>> {
  try {
    const value = await fn()
    return { value, error: null, fellBack: false }
  } catch (e: any) {
    return { value: fallback, error: e?.message ?? 'Unknown error', fellBack: true }
  }
}

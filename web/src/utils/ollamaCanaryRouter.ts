/**
 * ollamaCanaryRouter.ts — Ollama 3.1 canary routing stub.
 * Routes requests between production and canary Ollama models.
 */
export const OLLAMA_CANARY_ENABLED = process.env.OLLAMA_CANARY_ENABLED === '1'
export const OLLAMA_CANARY_PERCENT = parseFloat(process.env.OLLAMA_CANARY_PERCENT ?? '0')

export function routeOllamaRequest(requestId: string, overridePercent?: number): 'canary' | 'production' {
  if (!OLLAMA_CANARY_ENABLED) return 'production'
  const pct = Math.max(0, Math.min(100, overridePercent ?? OLLAMA_CANARY_PERCENT))
  const hash = Array.from(requestId).reduce((h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0, 0)
  return (Math.abs(hash) % 10000) < pct * 100 ? 'canary' : 'production'
}

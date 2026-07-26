import { ref, computed } from 'vue'
import { useFleetWebSocket } from './useFleetWebSocket'

export interface CascadeDataPoint {
  confidence: number
  model_tier: string | null
  slug: string | null
  timestamp: string
}

export function useCascadeStream(historySize = 50) {
  const stream = ref<CascadeDataPoint[]>([])
  const { on } = useFleetWebSocket()

  on('cascade:update', (payload: any) => {
    const point: CascadeDataPoint = {
      confidence: payload.confidence ?? 0,
      model_tier: payload.model_tier ?? null,
      slug: payload.slug ?? null,
      timestamp: new Date().toISOString(),
    }
    stream.value = [point, ...stream.value.slice(0, historySize - 1)]
  })

  function getConfidenceTrend(windowSize = 10): number[] {
    return stream.value.slice(0, windowSize).map(p => p.confidence).reverse()
  }

  function getAverageConfidence(windowSize = 10): number {
    const window = stream.value.slice(0, windowSize)
    if (!window.length) return 0
    return window.reduce((s, p) => s + p.confidence, 0) / window.length
  }

  function getEscalationRate(windowSize = 20): number {
    const window = stream.value.slice(0, windowSize)
    if (!window.length) return 0
    const cheap = window.filter(p => p.confidence < 0.6).length
    return Math.round((cheap / window.length) * 100)
  }

  const latestConfidence = computed(() => stream.value[0]?.confidence ?? 0)
  const latestModel = computed(() => stream.value[0]?.model_tier ?? null)

  return { stream, latestConfidence, latestModel, getConfidenceTrend, getAverageConfidence, getEscalationRate }
}

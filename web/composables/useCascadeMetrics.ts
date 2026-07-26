import { ref, computed } from 'vue'

export interface CascadeMetrics {
  totalCascades: number
  activeCascades: number
  completedToday: number
  failedToday: number
  avgDurationMs: number
  successRate: number
}

export function useCascadeMetrics() {
  const metrics = ref<CascadeMetrics>({
    totalCascades: 0,
    activeCascades: 0,
    completedToday: 0,
    failedToday: 0,
    avgDurationMs: 0,
    successRate: 0
  })

  const isLoading = ref(false)

  const formattedAvgDuration = computed(() => {
    const ms = metrics.value.avgDurationMs
    if (ms < 1000) return `${ms}ms`
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
    return `${(ms / 60000).toFixed(1)}m`
  })

  const successRateColor = computed(() => {
    const rate = metrics.value.successRate
    if (rate >= 95) return 'text-emerald-400'
    if (rate >= 80) return 'text-amber-400'
    return 'text-red-400'
  })

  async function fetchMetrics() {
    isLoading.value = true
    try {
      const data = await $fetch<CascadeMetrics>('/api/terminal/metrics')
      metrics.value = data
    } catch {
      // Keep existing or default metrics
    } finally {
      isLoading.value = false
    }
  }

  return {
    metrics,
    isLoading,
    formattedAvgDuration,
    successRateColor,
    fetchMetrics
  }
}

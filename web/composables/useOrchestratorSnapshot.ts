import { ref, onMounted, onUnmounted } from 'vue'

export interface OrchestratorSnapshot {
  timestamp: string
  queue_states: Record<string, number>
  running_tasks: Array<{
    slug: string
    account: string | null
    project_id: string | null
    updated_at: string
    model_tier: string | null
    cascade_confidence: number | null
    kind: string | null
  }>
  recent_completions: Array<{
    slug: string
    state: string
    updated_at: string
    cost_usd: number | null
    kind: string | null
    project_id: string | null
    artifact_commit: string | null
  }>
  total_queued: number
  total_running: number
  total_blocked: number
  cascade: {
    avg_confidence: number
    saves_percent: number
    active_tasks: number
  }
  metrics: {
    total_cost_usd: number
    completed_count: number
    cheap_model_rate: number
  }
}

const EMPTY_SNAPSHOT: OrchestratorSnapshot = {
  timestamp: '',
  queue_states: {},
  running_tasks: [],
  recent_completions: [],
  total_queued: 0,
  total_running: 0,
  total_blocked: 0,
  cascade: { avg_confidence: 0, saves_percent: 0, active_tasks: 0 },
  metrics: { total_cost_usd: 0, completed_count: 0, cheap_model_rate: 0 },
}

export function useOrchestratorSnapshot(intervalMs = 2000) {
  const snapshot = ref<OrchestratorSnapshot>({ ...EMPTY_SNAPSHOT })
  const loading = ref(true)
  const error = ref<string | null>(null)
  let timer: ReturnType<typeof setInterval> | null = null

  async function refresh() {
    try {
      const data = await $fetch<OrchestratorSnapshot>('/api/orchestrator/snapshot')
      snapshot.value = data
      error.value = null
    } catch (e: any) {
      error.value = e?.message ?? 'Failed to fetch snapshot'
    } finally {
      loading.value = false
    }
  }

  function start() {
    refresh()
    timer = setInterval(refresh, intervalMs)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onMounted(start)
  onUnmounted(stop)

  return { snapshot, loading, error, refresh }
}

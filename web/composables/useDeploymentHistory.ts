import { ref } from 'vue'

export interface DeployRecord {
  id: string
  project: string
  version: string
  status: 'success' | 'failed' | 'rolled_back'
  startedAt: string
  completedAt: string | null
  triggeredBy: string
  commitHash: string
}

export function useDeploymentHistory() {
  const history = ref<DeployRecord[]>([])
  const isLoading = ref(false)

  async function fetchHistory(project?: string, limit = 20) {
    isLoading.value = true
    try {
      const data = await $fetch<{ records: DeployRecord[] }>('/api/terminal/deploy-history', {
        params: { project, limit }
      })
      history.value = data.records
    } catch {
      // Keep existing history
    } finally {
      isLoading.value = false
    }
  }

  function getLatestForProject(project: string): DeployRecord | undefined {
    return history.value.find(r => r.project === project)
  }

  return {
    history,
    isLoading,
    fetchHistory,
    getLatestForProject
  }
}

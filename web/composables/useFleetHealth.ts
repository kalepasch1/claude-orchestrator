import type { FleetHealth, FleetHealthComposable } from '~/types/fleet-health'

export function useFleetHealth(): FleetHealthComposable {
  const dbUp = ref<boolean | null>(null)
  const health = ref<FleetHealth | null>(null)
  const supabase = useSupabaseClient<any>()

  async function refresh(): Promise<void> {
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const response = await $fetch<FleetHealth>('/api/fleet-health', {
        headers: session?.access_token
          ? { authorization: `Bearer ${session.access_token}` }
          : undefined,
      })
      health.value = response
      dbUp.value = response?.db_up === true
    } catch {
      health.value = {
        db_up: false,
        status: 'unknown',
        heartbeat_seconds: null,
        machines_live: 0,
        contract_consistent: false,
      }
      dbUp.value = false
    }
  }

  return { dbUp, health, refresh }
}

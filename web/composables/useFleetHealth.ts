import type { FleetHealth, FleetHealthComposable } from '~/types/fleet-health'

export function useFleetHealth(): FleetHealthComposable {
  const dbUp = ref<boolean | null>(null)
  const supabase = useSupabaseClient<any>()

  async function refresh(): Promise<void> {
    try {
      const { data: { session } } = await supabase.auth.getSession()
      const response = await $fetch<FleetHealth>('/api/fleet-health', {
        headers: session?.access_token
          ? { authorization: `Bearer ${session.access_token}` }
          : undefined,
      })
      dbUp.value = response?.db_up === true
    } catch {
      dbUp.value = false
    }
  }

  return { dbUp, refresh }
}

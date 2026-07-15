import type { GuidanceCandidate, PreActionGuidance } from '@darwin/kernel/fleetAdmin'
let confirmedAction: null | (() => void | Promise<void>) = null
export function usePreActionGuidance() {
  const supabase = useSupabaseClient<any>()
  const open = useState('pre-action:open', () => false), loading = useState('pre-action:loading', () => false)
  const candidate = useState<GuidanceCandidate | null>('pre-action:candidate', () => null), guidance = useState<PreActionGuidance | null>('pre-action:guidance', () => null), error = useState('pre-action:error', () => '')
  async function preview(next: GuidanceCandidate, action: () => void | Promise<void>) { candidate.value = next; guidance.value = null; error.value = ''; open.value = true; loading.value = true; confirmedAction = action; try { const { data: { session } } = await supabase.auth.getSession(); guidance.value = await $fetch('/api/fleet/guidance', { method: 'POST', body: next, headers: session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {} }) } catch (e: any) { error.value = e?.data?.message || e?.message || 'Guidance is unavailable. Nothing has run.' } finally { loading.value = false } }
  async function confirm() { if (!guidance.value || guidance.value.recommendation === 'do_not_proceed' || !confirmedAction) return; const action = confirmedAction; confirmedAction = null; open.value = false; await action() }
  function cancel() { confirmedAction = null; open.value = false }
  return { open, loading, candidate, guidance, error, preview, confirm, cancel }
}

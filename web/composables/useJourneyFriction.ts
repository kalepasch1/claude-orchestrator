interface FrictionState { visits: number; abandonments: number; longDwells: number; configurationChurn: number; completed: number }
const EMPTY: FrictionState = { visits: 0, abandonments: 0, longDwells: 0, configurationChurn: 0, completed: 0 }

export function useJourneyFriction(surface: MaybeRefOrGetter<string>) {
  const state = reactive<FrictionState>({ ...EMPTY })
  const startedAt = ref(0)
  const completedThisVisit = ref(false)
  const key = computed(() => `madeus:friction:${toValue(surface)}`)
  const simplified = computed(() => state.abandonments >= 2 || state.longDwells >= 3 || state.configurationChurn >= 4)
  function persist() { if (import.meta.client) localStorage.setItem(key.value, JSON.stringify(state)) }
  function complete() { completedThisVisit.value = true; state.completed++; persist() }
  function churn() { state.configurationChurn++; persist() }
  function leave() {
    const dwell = Date.now() - startedAt.value
    if (!completedThisVisit.value && dwell > 15_000) state.abandonments++
    if (dwell > 90_000) state.longDwells++
    persist()
  }
  onMounted(() => {
    try { Object.assign(state, JSON.parse(localStorage.getItem(key.value) || '{}')) } catch {}
    state.visits++
    startedAt.value = Date.now()
    persist()
    window.addEventListener('pagehide', leave)
  })
  onUnmounted(() => { window.removeEventListener('pagehide', leave); leave() })
  return { state, simplified, complete, churn }
}

import { deriveProficiency, EMPTY_PROFICIENCY, type ProficiencySignals } from '~/utils/adaptiveProficiency'

export function useAdaptiveProficiency(surface: MaybeRefOrGetter<string>) {
  const hydrated = ref(false)
  const signals = reactive<ProficiencySignals>({ ...EMPTY_PROFICIENCY })
  const key = computed(() => `madeus:proficiency:${toValue(surface)}`)
  const profile = computed(() => deriveProficiency(signals))

  function persist() {
    if (!import.meta.client || !hydrated.value) return
    localStorage.setItem(key.value, JSON.stringify(signals))
  }
  function record(event: 'visit' | 'completed' | 'expanded' | 'advanced') {
    if (event === 'visit') signals.visits++
    else if (event === 'completed') signals.completedActions++
    else if (event === 'expanded') signals.expandedGuidance++
    else signals.advancedUses++
    persist()
  }
  onMounted(() => {
    try { Object.assign(signals, JSON.parse(localStorage.getItem(key.value) || '{}')) } catch {}
    hydrated.value = true
    record('visit')
  })
  watch(signals, persist, { deep: true })
  return { profile, record, hydrated }
}


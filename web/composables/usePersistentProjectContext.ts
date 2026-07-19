type MadeusContext = {
  projectId: string
  appId: string
  capability: string
  advanced: boolean
  successCriteria: string
  constraints: string
}

const DEFAULT_CONTEXT: MadeusContext = {
  projectId: '', appId: '', capability: '', advanced: false,
  successCriteria: '', constraints: '',
}

export function usePersistentProjectContext(scope: Ref<string> | ComputedRef<string>) {
  const context = reactive<MadeusContext>({ ...DEFAULT_CONTEXT })
  const hydrated = ref(false)
  const storageKey = computed(() => `madeus:workspace:${scope.value}`)

  function hydrate() {
    if (!import.meta.client) return
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey.value) || '{}')
      Object.assign(context, DEFAULT_CONTEXT, saved)
    } catch { Object.assign(context, DEFAULT_CONTEXT) }
    hydrated.value = true
  }

  function persist() {
    if (!import.meta.client || !hydrated.value) return
    localStorage.setItem(storageKey.value, JSON.stringify({ ...context, updatedAt: new Date().toISOString() }))
  }

  watch(storageKey, hydrate)
  watch(context, persist, { deep: true })
  onMounted(hydrate)
  return { context, hydrated, hydrate, persist }
}

<script setup lang="ts">
import { nextBestActions, type OperatorObjective, type OperatorRole } from '~/utils/adaptiveNavigation'
const props = defineProps<{ runnerCount: number; pendingApprovals: number; blockedTasks: number; readyConnectors: number }>()
const user = useSupabaseUser() as any
const supabase = useSupabaseClient<any>()
const guidanceEnabled = useState('adaptive-guidance', () => true)
const objective = useState<OperatorObjective>('adaptive-objective', () => 'operate')
const initialized = ref(false)
const inheritedRole = ref<OperatorRole | null>(null), inheritedPermissions = ref<string[]>([]), learnedRoutes = ref<Array<{ route: string; visits: number }>>([])
const role = computed<OperatorRole>(() => inheritedRole.value || (() => {
  const value = String(user.value?.app_metadata?.role || user.value?.user_metadata?.role || 'operator')
  return ['admin', 'operator', 'reviewer', 'engineer', 'analyst', 'new_user'].includes(value) ? value as OperatorRole : 'operator'
})())
const permissions = computed<string[]>(() => inheritedPermissions.value.length ? inheritedPermissions.value : Array.isArray(user.value?.app_metadata?.permissions) ? user.value.app_metadata.permissions : [])
const suggestions = computed(() => nextBestActions({ role: role.value, objective: objective.value, permissions: permissions.value, learnedRoutes: learnedRoutes.value, ...props }))
function persist() { if (!import.meta.client) return; localStorage.setItem('orchestrator:adaptive-guidance', String(guidanceEnabled.value)); localStorage.setItem('orchestrator:objective', objective.value) }
onMounted(async () => { guidanceEnabled.value = localStorage.getItem('orchestrator:adaptive-guidance') !== 'false'; const saved = localStorage.getItem('orchestrator:objective') as OperatorObjective | null; if (saved && ['operate', 'ship', 'govern', 'connect', 'learn'].includes(saved)) objective.value = saved; try { const { data: { session } } = await supabase.auth.getSession(); const context = await $fetch<any>('/api/adaptive/context', { headers: session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {} }); inheritedRole.value = context.role === 'member' ? 'new_user' : context.role; inheritedPermissions.value = context.passport?.permissions || []; learnedRoutes.value = context.learned_routes || []; if (!saved && context.passport?.default_objective) objective.value = context.role === 'member' ? 'learn' : context.passport.default_objective } catch {} initialized.value = true })
watch([guidanceEnabled, objective], () => { if (initialized.value) persist() })
</script>

<template>
  <section v-if="guidanceEnabled && suggestions[0]" class="adaptive-focus">
    <div class="adaptive-label"><span>Suggested next</span><button :aria-pressed="guidanceEnabled" aria-label="Hide adaptive guidance" @click="guidanceEnabled = false">×</button></div>
    <NuxtLink :to="suggestions[0].to" class="adaptive-primary" :class="{ urgent: suggestions[0].urgent }"><b>{{ suggestions[0].label }}</b><span>↗</span><small>{{ suggestions[0].reason }}</small></NuxtLink>
    <details v-if="suggestions.length > 1"><summary>{{ suggestions.length - 1 }} more suggestion{{ suggestions.length === 2 ? '' : 's' }}</summary><NuxtLink v-for="item in suggestions.slice(1)" :key="item.to" :to="item.to">{{ item.label }} <span>↗</span></NuxtLink></details>
  </section>
  <button v-else class="adaptive-enable" @click="guidanceEnabled = true">✦ Show guidance</button>
</template>

<script setup lang="ts">
import { CAPABILITY_DESTINATIONS } from '~/config/orchestratorCapabilities'

const supabase = useSupabaseClient<any>()
const route = useRoute()
const { track } = useExperienceTelemetry('universal-command')
const open = ref(false)
const command = ref('')
const loading = ref(false)
const result = ref<any>(null)
const error = ref('')
const activeIndex = ref(0)
const openedAt = ref(0)

const destinations = [
  { label: 'What should we accomplish?', description: 'Route any outcome automatically', to: '/orchestrators', keywords: ['start', 'command', 'autopilot'] },
  { label: 'Connections', description: 'Connect specialist tools and accounts', to: '/connectors', keywords: ['apps', 'tools', 'vendors', 'figma', 'adobe'] },
  { label: 'Sign-offs', description: 'Review decisions that require you', to: '/sign-offs', keywords: ['approval', 'review', 'decision'] },
  { label: 'Portfolio activity', description: 'See work in progress and evidence', to: '/queue', keywords: ['tasks', 'history', 'proof'] },
  ...CAPABILITY_DESTINATIONS,
]

const suggestions = computed(() => {
  const terms = command.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return destinations.slice(0, 7)
  return destinations.map(item => {
    const haystack = `${item.label} ${item.description} ${item.keywords.join(' ')}`.toLowerCase()
    return { ...item, score: terms.reduce((score, term) => score + (haystack.includes(term) ? 1 : 0), 0) }
  }).filter(item => item.score).sort((a, b) => b.score - a.score).slice(0, 7)
})

function show() {
  open.value = true
  openedAt.value = Date.now()
  activeIndex.value = 0
  track('action_started', { trigger: 'palette_open', route: route.path })
}

function close(reason = 'dismissed') {
  if (open.value) track('guidance_dismissed', { reason, dwell_ms: Date.now() - openedAt.value, query_length: command.value.length })
  open.value = false
  result.value = null
  error.value = ''
}

async function choose(item: typeof destinations[number]) {
  track('action_completed', { trigger: 'instant_destination', destination: item.to, query: command.value.slice(0, 80), dwell_ms: Date.now() - openedAt.value })
  close('navigated')
  command.value = ''
  await navigateTo(item.to)
}

async function run() {
  if (!command.value.trim()) return
  if (suggestions.value[activeIndex.value]) return choose(suggestions.value[activeIndex.value])
  loading.value = true
  error.value = ''
  try {
    const { data: { session } } = await supabase.auth.getSession()
    const response: any = await $fetch('/api/constitution/action', { method: 'POST', body: { action: 'command', values: { command: command.value } }, headers: session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {} })
    result.value = response.command
    track('guidance_followed', { trigger: 'governed_resolution', capability: result.value?.capability, dwell_ms: Date.now() - openedAt.value })
  } catch (e: any) { error.value = e?.data?.message || e?.message || 'Madeus could not resolve this command.' }
  finally { loading.value = false }
}

async function go() {
  if (!result.value?.destination) return
  const destination = result.value.destination
  track('action_completed', { trigger: 'governed_destination', destination, capability: result.value.capability })
  close('navigated')
  command.value = ''
  await navigateTo(destination)
}

function keys(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); open.value ? close() : show(); return }
  if (!open.value) return
  if (event.key === 'Escape') close()
  if (event.key === 'ArrowDown') { event.preventDefault(); activeIndex.value = Math.min(activeIndex.value + 1, suggestions.value.length - 1) }
  if (event.key === 'ArrowUp') { event.preventDefault(); activeIndex.value = Math.max(activeIndex.value - 1, 0) }
}
watch(command, () => { activeIndex.value = 0; result.value = null })
onMounted(() => window.addEventListener('keydown', keys))
onUnmounted(() => window.removeEventListener('keydown', keys))
</script>

<template>
  <button type="button" class="command-trigger" aria-label="Open universal command" aria-haspopup="dialog" :aria-expanded="open" @click="show"><span>⌘K</span> Command</button>
  <div v-if="open" class="command-backdrop" role="dialog" aria-modal="true" aria-label="Universal capability command" @mousedown.self="close()">
    <section class="command-dialog">
      <header><div><span>Universal capability command</span><h2>Go anywhere. Accomplish anything.</h2></div><button type="button" aria-label="Close universal command" @click="close()">×</button></header>
      <form class="command-input" @submit.prevent="run"><span>⌕</span><input v-model="command" autofocus aria-label="Search capabilities or describe an outcome" placeholder="Search capabilities or describe an outcome…"><kbd>↵</kbd></form>
      <div v-if="suggestions.length" class="command-results"><button v-for="(item, index) in suggestions" :key="`${item.to}:${item.label}`" type="button" :class="{ active: index === activeIndex }" @mouseenter="activeIndex = index" @click="choose(item)"><span><b>{{ item.label }}</b><small>{{ item.description }}</small></span><i>↗</i></button></div>
      <div v-else-if="!result" class="command-resolve"><p>No exact destination found. Madeus can interpret the outcome, create a proof envelope, and select the right workspace.</p><button :disabled="loading" @click="run">{{ loading ? 'Resolving…' : 'Route this outcome' }} →</button></div>
      <p v-if="error" class="command-error">{{ error }}</p>
      <article v-if="result" class="command-proof"><span>{{ result.capability }} → {{ result.destination }}</span><h3>{{ result.explanation.why }}</h3><p>Least privilege: {{ result.explanation.scopes.join(', ') }} · proof {{ result.proof.digest.slice(0, 12) }}… · {{ result.proof.status }}</p><div><button type="button" @click="result = null">Revise</button><button type="button" @click="go">Open canonical destination</button></div></article>
      <footer><span>↑↓ Navigate</span><span>↵ Open</span><span>Esc Close</span><b>Routing and permissions remain automatic</b></footer>
    </section>
  </div>
</template>

<style scoped>
.command-trigger{position:fixed;right:18px;bottom:18px;z-index:40;border:1px solid #d7ddd8;border-radius:99px;padding:9px 13px;background:#fff;box-shadow:0 12px 38px #173b2918;color:#4f5b53;font-size:10px}.command-trigger span{margin-right:6px;color:#194c36;font-weight:750}.command-backdrop{position:fixed;inset:0;z-index:150;padding:11vh 18px 18px;background:#14271d66;backdrop-filter:blur(6px)}.command-dialog{width:min(680px,100%);margin:auto;overflow:hidden;border:1px solid #d6ddd8;border-radius:18px;background:#fff;box-shadow:0 35px 100px #112d2040}.command-dialog>header{display:flex;justify-content:space-between;align-items:start;padding:20px 20px 14px}.command-dialog header span{font-size:9px;font-weight:750;letter-spacing:.15em;text-transform:uppercase;color:#194c36}.command-dialog h2{margin-top:4px;font-size:17px;letter-spacing:-.025em}.command-dialog header button{border:0;background:none;color:#777;font-size:18px}.command-input{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;margin:0 14px;padding:12px 13px;border:1px solid #bdcec2;border-radius:11px;box-shadow:0 0 0 3px #edf3ee}.command-input input{border:0;outline:0;font-size:14px}.command-input kbd{border:1px solid #ddd;border-radius:5px;padding:2px 5px;background:#f6f6f3;color:#777;font-size:9px}.command-results{display:grid;gap:2px;padding:10px 14px}.command-results button{display:flex;justify-content:space-between;align-items:center;border:0;border-radius:9px;padding:10px;background:#fff;text-align:left}.command-results button.active{background:#edf3ee}.command-results b,.command-results small{display:block}.command-results b{font-size:11px}.command-results small{margin-top:3px;color:#7b827d;font-size:9px}.command-results i{color:#194c36;font-style:normal}.command-resolve{display:flex;justify-content:space-between;gap:20px;align-items:center;margin:10px 14px;padding:14px;border-radius:10px;background:#edf3ee}.command-resolve p{max-width:470px;font-size:10px;line-height:1.55;color:#536158}.command-resolve button,.command-proof div button:last-child{border:0;border-radius:8px;padding:9px 12px;background:#194c36;color:#fff;font-size:10px;white-space:nowrap}.command-error{margin:8px 18px;color:#a33;font-size:10px}.command-proof{margin:10px 14px;padding:15px;border:1px solid #bfd2c4;border-radius:11px;background:#f2f7f3}.command-proof>span{font-size:9px;font-weight:700;color:#194c36}.command-proof h3{margin-top:5px;font-size:12px}.command-proof p{margin-top:5px;font-size:9px;color:#68716b}.command-proof div{display:flex;justify-content:flex-end;gap:7px;margin-top:12px}.command-proof div button{border:1px solid #d4d8d5;border-radius:8px;padding:8px 11px;background:#fff;font-size:9px}.command-dialog>footer{display:flex;gap:14px;align-items:center;padding:10px 18px;border-top:1px solid #e6e8e4;background:#fafbf9;color:#8a908c;font-size:8px}.command-dialog footer b{margin-left:auto;color:#55705f}@media(max-width:600px){.command-backdrop{padding:6vh 10px 10px}.command-resolve{align-items:flex-start;flex-direction:column}.command-dialog>footer b{display:none}}
</style>

<script setup lang="ts">
definePageMeta({ layout: 'default' })

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

async function authedFetch<T = any>(url: string, opts: any = {}): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, {
    ...opts,
    headers: { ...(opts.headers || {}), ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}) },
  })
}

const tasks = ref<any[]>([])
const projects = ref<any[]>([])
const loading = ref(false)
const stopLoading = ref(false)
const globalPaused = ref(false)
const queueLoading = ref(false)
const stateFilter = ref('all')
const expandedTask = ref<string | null>(null)
const nlQuery = ref('')
const nlAnswer = ref('')
const nlLoading = ref(false)

const newTask = reactive({ project_id: '', slug: '', prompt: '', kind: 'build' })

const STATES = ['QUEUED', 'RUNNING', 'RETRY', 'BLOCKED', 'CONFLICT', 'TESTFAIL', 'DONE', 'MERGED', 'SHELVED']
const RELEASE_FIX_PREFIXES = ['relfix-', 'qafix-', 'deployfix-', 'buildfix-']

// Exact counts from DB
const counts = ref<Record<string, number>>({})
async function loadCounts() {
  const results = await Promise.all(
    STATES.map(async s => {
      const { count } = await supabase.from('tasks').select('id', { count: 'exact', head: true }).eq('state', s)
      return [s, count || 0] as const
    })
  )
  counts.value = Object.fromEntries(results)
}

async function loadPriorityQueues() {
  const [recovery, relfix, improve, canary] = await Promise.all([
    supabase.from('tasks').select('id', { count: 'exact', head: true }).like('slug', 'recover-%').eq('state', 'QUEUED'),
    Promise.all(RELEASE_FIX_PREFIXES.map(p => supabase.from('tasks').select('id', { count: 'exact', head: true }).like('slug', `${p}%`).eq('state', 'QUEUED'))),
    supabase.from('tasks').select('id', { count: 'exact', head: true }).like('slug', 'improve-%').eq('state', 'QUEUED'),
    supabase.from('tasks').select('id', { count: 'exact', head: true }).like('slug', 'canary-%').in('state', ['QUEUED', 'RUNNING']),
  ])
  priorityCounts.value = {
    recovery: recovery.count || 0,
    relfix: relfix.reduce((n, r) => n + (r.count || 0), 0),
    improve: improve.count || 0,
    canary: canary.count || 0,
  }
}

const priorityCounts = ref({ recovery: 0, relfix: 0, improve: 0, canary: 0 })

async function loadTasks() {
  const q = stateFilter.value === 'all'
    ? supabase.from('tasks').select('*').order('created_at', { ascending: false }).limit(100)
    : supabase.from('tasks').select('*').eq('state', stateFilter.value).order('created_at', { ascending: false }).limit(100)
  const { data } = await q
  tasks.value = data || []
}

async function loadAll() {
  loading.value = true
  const [p, ctrl] = await Promise.all([
    supabase.from('projects').select('*').order('name'),
    supabase.from('controls').select('*'),
  ])
  projects.value = p.data || []
  globalPaused.value = (ctrl.data || []).some((c: any) => c.scope === 'global' && c.paused)
  if (!newTask.project_id && (p.data || []).length) newTask.project_id = p.data![0].id
  await Promise.all([loadCounts(), loadPriorityQueues(), loadTasks()])
  loading.value = false
}

watch(stateFilter, () => loadTasks())

function makeSlug(text: string) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48) || `task-${Date.now()}`
}
function optimizedPrompt(text: string, projectName: string) {
  return `USER-DRIVEN IMPROVEMENT for ${projectName || 'selected app'}\n\n${text.trim()}\n\nRoute through orchestration pipeline: triage → plan → code → QA → dev-merge → release.`
}

async function queueTask() {
  if (!newTask.project_id || !newTask.prompt.trim()) return
  queueLoading.value = true
  try {
    const project = projects.value.find((p: any) => p.id === newTask.project_id)
    const slug = newTask.slug || makeSlug(newTask.prompt)
    await supabase.from('tasks').insert({
      project_id: newTask.project_id, slug,
      prompt: optimizedPrompt(newTask.prompt, project?.name || ''),
      kind: newTask.kind, state: 'QUEUED',
      note: 'pipeline:dashboard-user-driven; triage-plan-code-qa-devmerge-release',
    })
    newTask.slug = ''; newTask.prompt = ''
    await loadAll()
  } finally { queueLoading.value = false }
}

async function stopAll() {
  stopLoading.value = true
  try {
    await supabase.from('controls').upsert({
      scope: 'global', project: null, paused: true,
      reason: 'manual stop from queue page', updated_by: user.value?.email,
      updated_at: new Date().toISOString(),
    }, { onConflict: 'scope,project' })
    globalPaused.value = true
  } finally { stopLoading.value = false }
}

async function resumeAll() {
  stopLoading.value = true
  try {
    await supabase.from('controls').upsert({
      scope: 'global', project: null, paused: false,
      updated_by: user.value?.email, updated_at: new Date().toISOString(),
    }, { onConflict: 'scope,project' })
    globalPaused.value = false
  } finally { stopLoading.value = false }
}

async function askNL() {
  if (!nlQuery.value.trim()) return
  nlLoading.value = true; nlAnswer.value = ''
  try {
    const { data } = await supabase.functions.invoke('ask', { body: { question: nlQuery.value } })
    nlAnswer.value = (data as any)?.answer || 'No answer returned.'
  } catch (e: any) { nlAnswer.value = 'Error: ' + e.message }
  nlLoading.value = false
}

function stateColor(state: string) {
  const s = (state || '').toUpperCase()
  if (s === 'RUNNING') return 'text-blue-600 bg-blue-50'
  if (s === 'DONE') return 'text-green-600 bg-green-50'
  if (s === 'MERGED') return 'text-emerald-600 bg-emerald-50'
  if (s === 'QUEUED') return 'text-amber-600 bg-amber-50'
  if (['BLOCKED', 'CONFLICT', 'TESTFAIL'].includes(s)) return 'text-red-600 bg-red-50'
  if (s === 'RETRY') return 'text-orange-600 bg-orange-50'
  return 'text-gray-500 bg-gray-100'
}

function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d/60)}h ago` : `${Math.round(d/1440)}d ago`
}

let sub: any = null
onMounted(async () => {
  if (user.value) await loadAll()
  sub = supabase.channel('queue-live')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'tasks' }, () => { loadCounts(); loadTasks() })
    .subscribe()
})
onUnmounted(() => { if (sub) supabase.removeChannel(sub) })
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen bg-white text-gray-900">
    <div class="max-w-6xl mx-auto px-6 py-6 space-y-6">

      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-bold text-gray-900">Queue Management</h1>
          <p class="text-sm text-gray-500 mt-0.5">Task pipeline state, controls, and submission</p>
        </div>
        <div class="flex gap-2">
          <button @click="globalPaused ? resumeAll() : stopAll()" :disabled="stopLoading"
            class="px-4 py-2 text-sm rounded-lg border transition-colors"
            :class="globalPaused ? 'border-green-700 text-green-400 hover:bg-green-400/10' : 'border-red-700 text-red-400 hover:bg-red-400/10'">
            {{ stopLoading ? '…' : globalPaused ? '▶ Resume All' : '⏹ Stop All' }}
          </button>
          <button @click="loadAll" class="px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-500 text-sm rounded-lg">↻</button>
        </div>
      </div>

      <!-- KPI Tiles -->
      <div class="grid grid-cols-3 sm:grid-cols-6 gap-3">
        <div v-for="s in STATES.slice(0,6)" :key="s" class="bg-gray-50 border border-gray-200 rounded-xl p-4 text-center">
          <div class="text-2xl font-bold font-mono" :class="stateColor(s).split(' ')[0]">{{ counts[s] ?? '—' }}</div>
          <div class="text-xs text-gray-500 mt-1">{{ s }}</div>
        </div>
      </div>

      <!-- Priority Queue Tiles -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="bg-gray-50 border border-gray-200 rounded-xl p-4">
          <div class="text-xl font-bold text-cyan-600 font-mono">{{ priorityCounts.recovery }}</div>
          <div class="text-xs text-gray-500 mt-1">Recovery queued</div>
        </div>
        <div class="bg-gray-50 border border-gray-200 rounded-xl p-4">
          <div class="text-xl font-bold font-mono" :class="priorityCounts.relfix ? 'text-red-600' : 'text-gray-500'">{{ priorityCounts.relfix }}</div>
          <div class="text-xs text-gray-500 mt-1">Release-fixes</div>
        </div>
        <div class="bg-gray-50 border border-gray-200 rounded-xl p-4">
          <div class="text-xl font-bold text-indigo-600 font-mono">{{ priorityCounts.improve }}</div>
          <div class="text-xs text-gray-500 mt-1">Improvements</div>
        </div>
        <div class="bg-gray-50 border border-gray-200 rounded-xl p-4">
          <div class="text-xl font-bold text-emerald-600 font-mono">{{ priorityCounts.canary }}</div>
          <div class="text-xs text-gray-500 mt-1">Canaries active</div>
        </div>
      </div>

      <!-- Queue Improvement Form -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200">
          <span class="text-sm font-semibold text-gray-900">Queue Task</span>
        </div>
        <div class="p-5 space-y-3">
          <div class="flex gap-3 flex-wrap">
            <select v-model="newTask.project_id" class="select-dark flex-1 min-w-32">
              <option value="" disabled>Project…</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <select v-model="newTask.kind" class="select-dark w-32">
              <option v-for="k in ['build','fix','research','qa','deploy','canary']" :key="k" :value="k">{{ k }}</option>
            </select>
          </div>
          <textarea v-model="newTask.prompt" rows="3" placeholder="Prompt / task description…"
            class="w-full bg-white border border-gray-300 rounded-lg px-4 py-3 text-sm text-gray-800 placeholder-gray-400 resize-none focus:outline-none focus:border-blue-500 font-mono">
          </textarea>
          <div class="flex gap-3">
            <input v-model="newTask.slug" type="text" placeholder="Slug (auto)"
              class="flex-1 bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:border-gray-300" />
            <button @click="queueTask" :disabled="queueLoading || !newTask.prompt.trim() || !newTask.project_id"
              class="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-gray-900 text-sm font-medium rounded-lg disabled:opacity-40 transition-colors">
              {{ queueLoading ? 'Queuing…' : '+ Queue' }}
            </button>
          </div>
        </div>
      </div>

      <!-- NL Search -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl p-4">
        <div class="flex gap-3">
          <input v-model="nlQuery" @keyup.enter="askNL" type="text" placeholder="Ask anything about the queue… (e.g. 'why are tasks blocked?')"
            class="flex-1 bg-white border border-gray-300 rounded-lg px-4 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:border-blue-500" />
          <button @click="askNL" :disabled="nlLoading"
            class="px-4 py-2 bg-gray-200 hover:bg-gray-200 text-gray-800 text-sm rounded-lg disabled:opacity-40 transition-colors">
            {{ nlLoading ? '…' : 'Ask' }}
          </button>
        </div>
        <div v-if="nlAnswer" class="mt-3 p-3 bg-white rounded-lg text-sm text-gray-700 border border-gray-200">{{ nlAnswer }}</div>
      </div>

      <!-- Task List -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 flex items-center gap-3">
          <span class="text-sm font-semibold text-gray-900">Tasks</span>
          <select v-model="stateFilter" class="select-dark text-xs">
            <option value="all">All states</option>
            <option v-for="s in STATES" :key="s" :value="s">{{ s }}</option>
          </select>
          <span class="text-xs text-gray-500 ml-auto">{{ tasks.length }} shown</span>
        </div>
        <div class="divide-y divide-gray-200/60">
          <div v-if="loading" class="px-5 py-8 text-center text-gray-400 text-sm">Loading…</div>
          <div v-else-if="tasks.length === 0" class="px-5 py-8 text-center text-gray-400 text-sm">No tasks found</div>
          <div v-for="t in tasks" :key="t.id"
            class="px-5 py-3 hover:bg-gray-50 transition-colors cursor-pointer"
            @click="expandedTask = expandedTask === t.id ? null : t.id">
            <div class="flex items-center gap-3">
              <span class="text-xs px-2 py-0.5 rounded-full font-mono font-medium flex-shrink-0" :class="stateColor(t.state)">{{ t.state }}</span>
              <span class="text-sm text-gray-800 font-mono truncate flex-1">{{ t.slug }}</span>
              <span v-if="t.model" class="text-xs text-gray-400 hidden md:block truncate max-w-28">{{ t.model }}</span>
              <span class="text-xs text-gray-400 flex-shrink-0">{{ t.created_at ? ago(t.created_at) : '' }}</span>
            </div>
            <div v-if="expandedTask === t.id" class="mt-3 p-3 bg-white rounded-lg border border-gray-200 space-y-2">
              <div class="text-xs text-gray-500">{{ t.prompt?.slice(0, 300) }}{{ t.prompt?.length > 300 ? '…' : '' }}</div>
              <pre v-if="t.log_tail" class="text-xs text-green-600 font-mono whitespace-pre-wrap overflow-x-auto max-h-40 overflow-y-auto">{{ t.log_tail }}</pre>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.select-dark {
  @apply bg-gray-100 border border-gray-300 text-gray-800 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 cursor-pointer;
}
</style>

<script setup lang="ts">
definePageMeta({ layout: 'default' })
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

const loops = ref<any[]>([])
const sessions = ref<any[]>([])
const projects = ref<any[]>([])
const recentPrunes = ref<any[]>([])
const feedbackItems = ref<any[]>([])
const resourceGauge = ref<any>({})
const sessionRunning = ref<Record<string, boolean>>({})
const feedbackSaving = ref(false)
const loading = ref(false)
const newFeedback = reactive({ category: 'other', severity: 'med', observation: '', suggestion: '' })

async function loadAll() {
  loading.value = true
  const [lps, sess, p, prunes, fb] = await Promise.all([
    supabase.from('loops').select('*').order('project'),
    supabase.from('session_actions').select('*').in('status', ['paused', 'finished']).order('created_at', { ascending: false }).limit(30),
    supabase.from('projects').select('*').order('name'),
    supabase.from('resource_events').select('kind,detail,action,created_at').eq('kind', 'prune').order('created_at', { ascending: false }).limit(10),
    supabase.from('orchestrator_feedback').select('category,severity,status').limit(500),
  ])
  loops.value = lps.data || []
  sessions.value = (sess.data || []).filter((s: any) => s.status !== 'paused')
  projects.value = p.data || []
  recentPrunes.value = prunes.data || []
  feedbackItems.value = fb.data || []
  const diskRow = (await supabase.from('resource_events').select('value,detail,created_at')
    .eq('kind', 'disk').order('created_at', { ascending: false }).limit(1)).data?.[0]
  if (diskRow) {
    const freeGb = parseFloat((diskRow.detail || '').match(/([\d.]+)GB/)?.[1] || '0')
    resourceGauge.value = { disk_pct: diskRow.value, free_gb: freeGb, ts: diskRow.created_at }
  }
  loading.value = false
}

async function toggleLoop(loop: any) {
  await supabase.from('loops').update({ enabled: !loop.enabled }).eq('id', loop.id)
  loop.enabled = !loop.enabled
}

async function runSession(sess: any) {
  if (!sess.next_action) return
  sessionRunning.value[sess.id] = true
  try {
    const proj = projects.value.find((p: any) => p.name === sess.project)
    if (!proj) { alert('Project not found'); return }
    await supabase.from('tasks').insert({
      project_id: proj.id, slug: `cont-${sess.session_id?.slice(0, 6) || 'sess'}`,
      prompt: sess.next_action, kind: 'build', state: 'QUEUED',
    })
    await supabase.from('session_actions').update({ status: 'queued' }).eq('id', sess.id)
    await loadAll()
  } finally { sessionRunning.value[sess.id] = false }
}

async function submitFeedback() {
  if (!newFeedback.observation.trim()) return
  feedbackSaving.value = true
  try {
    await supabase.from('orchestrator_feedback').insert({
      category: newFeedback.category, severity: newFeedback.severity,
      observation: newFeedback.observation, suggestion: newFeedback.suggestion,
      source: 'human', status: 'new',
    })
    newFeedback.observation = ''; newFeedback.suggestion = ''
    await loadAll()
  } finally { feedbackSaving.value = false }
}

const loopsByType = computed(() => {
  const m: Record<string, any[]> = {}
  for (const l of loops.value) { const t = l.type || 'other'; (m[t] ??= []).push(l) }
  return m
})

const feedbackStats = computed(() => {
  const cats: Record<string, number> = {}
  let newCount = 0
  for (const f of feedbackItems.value) {
    cats[f.category] = (cats[f.category] || 0) + 1
    if (f.status === 'new') newCount++
  }
  return { cats, newCount, total: feedbackItems.value.length }
})

function healthColor(h: string) {
  if (h === 'healthy') return 'text-green-600'
  if (h === 'degraded') return 'text-amber-600'
  if (h === 'down') return 'text-red-600'
  return 'text-gray-400'
}
function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d/60)}h ago` : `${Math.round(d/1440)}d ago`
}

onMounted(() => { if (user.value) loadAll() })
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen bg-white text-gray-900">
    <div class="max-w-5xl mx-auto px-6 py-6 space-y-6">

      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-bold text-gray-900">Loops</h1>
          <p class="text-sm text-gray-500 mt-0.5">Automation loop management and sessions</p>
        </div>
        <button @click="loadAll" class="px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-500 text-sm rounded-lg">↻ Refresh</button>
      </div>

      <CompoundingIntelligence compact />

      <!-- Loop summary by type -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div v-for="(loopList, type) in loopsByType" :key="type" class="bg-gray-50 border border-gray-200 rounded-xl p-4">
          <div class="text-lg font-bold text-gray-900 font-mono">{{ loopList.length }}</div>
          <div class="text-xs text-gray-500 mt-0.5">{{ type }}</div>
          <div class="text-xs mt-1" :class="loopList.every(l => l.health === 'healthy') ? 'text-green-600' : 'text-amber-600'">
            {{ loopList.filter(l => l.health === 'healthy').length }}/{{ loopList.length }} healthy
          </div>
        </div>
      </div>

      <!-- Loops table -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200">
          <span class="text-sm font-semibold text-gray-900">All Loops</span>
          <span class="text-xs text-gray-500 ml-2">{{ loops.length }} total</span>
        </div>
        <div v-if="loading" class="px-5 py-8 text-center text-gray-400 text-sm">Loading…</div>
        <table v-else class="w-full text-sm">
          <thead class="border-b border-gray-200">
            <tr class="text-xs text-gray-500 uppercase tracking-wide">
              <th class="px-5 py-2 text-left">Project</th>
              <th class="px-5 py-2 text-left">Type</th>
              <th class="px-5 py-2 text-left">Health</th>
              <th class="px-5 py-2 text-left">Cadence</th>
              <th class="px-5 py-2 text-right">Toggle</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            <tr v-for="l in loops" :key="l.id" class="hover:bg-gray-50">
              <td class="px-5 py-2.5 text-gray-700">{{ l.project }}</td>
              <td class="px-5 py-2.5 text-xs text-gray-500">{{ l.type }}</td>
              <td class="px-5 py-2.5 text-xs" :class="healthColor(l.health)">{{ l.health || '—' }}</td>
              <td class="px-5 py-2.5 text-xs font-mono text-gray-500">{{ l.cadence_seconds ? `${l.cadence_seconds}s` : '—' }}</td>
              <td class="px-5 py-2.5 text-right">
                <button @click="toggleLoop(l)" class="px-3 py-1 text-xs rounded-full border transition-colors"
                  :class="l.enabled ? 'border-green-700 text-green-600 hover:bg-green-400/10' : 'border-gray-300 text-gray-500 hover:bg-gray-200'">
                  {{ l.enabled ? 'on' : 'off' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Sessions panel -->
      <div v-if="sessions.length > 0" class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200">
          <span class="text-sm font-semibold text-gray-900">Paused/Finished Sessions</span>
          <span class="text-xs text-gray-500 ml-2">{{ sessions.length }}</span>
        </div>
        <div class="divide-y divide-gray-200">
          <div v-for="s in sessions" :key="s.id" class="px-5 py-3 flex items-start gap-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-xs text-gray-500">{{ s.project }}</span>
                <span class="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{{ s.status }}</span>
              </div>
              <div class="text-sm text-gray-700 truncate">{{ s.next_action || s.summary }}</div>
              <div class="text-xs text-gray-400 mt-0.5">{{ s.created_at ? ago(s.created_at) : '' }}</div>
            </div>
            <button v-if="s.next_action" @click="runSession(s)" :disabled="sessionRunning[s.id]"
              class="px-3 py-1.5 bg-blue-600/30 hover:bg-blue-600/50 text-blue-600 text-xs rounded-lg border border-blue-800/40 transition-colors disabled:opacity-40 flex-shrink-0">
              {{ sessionRunning[s.id] ? 'Queuing…' : '▶ Run it' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Resources panel -->
      <div v-if="resourceGauge.disk_pct != null || recentPrunes.length > 0" class="bg-gray-50 border border-gray-200 rounded-xl p-5 space-y-4">
        <div class="text-sm font-semibold text-gray-900">Resources</div>
        <div v-if="resourceGauge.disk_pct != null" class="space-y-1">
          <div class="flex justify-between text-xs text-gray-500">
            <span>Disk usage</span>
            <span class="font-mono">{{ Math.round(resourceGauge.disk_pct * 100) }}% · {{ resourceGauge.free_gb }}GB free</span>
          </div>
          <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
            <div class="h-full rounded-full" :style="`width: ${Math.min(100, resourceGauge.disk_pct * 100)}%`"
              :class="resourceGauge.disk_pct > 0.9 ? 'bg-red-500' : resourceGauge.disk_pct > 0.7 ? 'bg-amber-500' : 'bg-blue-500'">
            </div>
          </div>
        </div>
        <div v-if="recentPrunes.length > 0">
          <div class="text-xs text-gray-500 mb-2">Recent prune events</div>
          <div class="space-y-1">
            <div v-for="p in recentPrunes" :key="p.created_at" class="text-xs text-gray-500 flex gap-2">
              <span class="text-gray-400">{{ p.created_at ? ago(p.created_at) : '' }}</span>
              <span>{{ p.action || p.detail }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Feedback form -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 flex items-center justify-between">
          <span class="text-sm font-semibold text-gray-900">Submit Feedback</span>
          <span v-if="feedbackStats.newCount > 0" class="text-xs text-amber-600">{{ feedbackStats.newCount }} unreviewed</span>
        </div>
        <div class="p-5 space-y-3">
          <div class="flex gap-3">
            <select v-model="newFeedback.category" class="select-dark flex-1">
              <option v-for="c in ['efficiency','quality','reliability','cost','other']" :key="c" :value="c">{{ c }}</option>
            </select>
            <select v-model="newFeedback.severity" class="select-dark w-28">
              <option v-for="s in ['low','med','high','critical']" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <textarea v-model="newFeedback.observation" rows="2" placeholder="What did you observe?"
            class="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-800 placeholder-gray-400 resize-none focus:outline-none focus:border-blue-500">
          </textarea>
          <textarea v-model="newFeedback.suggestion" rows="2" placeholder="Suggestion (optional)"
            class="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-800 placeholder-gray-400 resize-none focus:outline-none focus:border-blue-500">
          </textarea>
          <button @click="submitFeedback" :disabled="feedbackSaving || !newFeedback.observation.trim()"
            class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-gray-900 text-sm rounded-lg disabled:opacity-40 transition-colors">
            {{ feedbackSaving ? 'Saving…' : 'Submit Feedback' }}
          </button>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.select-dark {
  @apply bg-gray-100 border border-gray-300 text-gray-800 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 cursor-pointer;
}
</style>

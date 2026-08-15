<script setup lang="ts">
// Wave-0 review gate (spec item 3): wave/merge timeline + one-click release review.
// The operator answers "do I release now or wait for the next wave" from this page.
definePageMeta({ layout: 'default' })

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

async function authedFetch<T = any>(url: string, opts: any = {}): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch(url, {
    ...opts,
    headers: { ...(opts.headers || {}), ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}) },
  }) as Promise<T>
}

const loading = ref(false)
const error = ref('')
const data = ref<any>(null)
const deciding = ref<string>('')

async function loadAll() {
  loading.value = true; error.value = ''
  try { data.value = await authedFetch('/api/waves') }
  catch (e: any) { error.value = e?.data?.message || e?.message || String(e) }
  finally { loading.value = false }
}

async function decide(card: any, status: 'approved' | 'denied') {
  const verb = status === 'approved' ? 'Approve' : 'Deny'
  const msg = status === 'approved'
    ? `${verb} this release wave for ${card.project}?\n\nAuthorizing promotes the staging batch to prod on the next release-train cycle. Authorization is not execution or completion.`
    : `${verb} this release wave for ${card.project}?\n\nThe batch stays on staging; nothing is lost. A fresh card is filed when staging changes.`
  if (!confirm(msg)) return
  const rationale = window.prompt('Rationale (optional — recorded as an attributed steering event):') || ''
  deciding.value = card.id
  try {
    await authedFetch('/api/approvals/decide', {
      method: 'POST',
      body: { id: card.id, status, authorizationBoundaryAcknowledged: status === 'approved', rationale },
    })
    await loadAll()
  } catch (e: any) { error.value = e?.data?.message || e?.message || String(e) }
  finally { deciding.value = '' }
}

function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d / 60)}h ago` : `${Math.round(d / 1440)}d ago`
}

const upcomingProjects = computed(() => Object.keys(data.value?.upcoming || {}).sort())
const runningProjects = computed(() => Object.keys(data.value?.running || {}).sort())

let sub: any = null
let timer: any = null
onMounted(async () => {
  if (user.value) await loadAll()
  sub = supabase.channel('waves-live')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'approvals' }, () => loadAll())
    .subscribe()
  timer = setInterval(() => { if (user.value) loadAll() }, 60_000)
})
onUnmounted(() => { if (sub) supabase.removeChannel(sub); if (timer) clearInterval(timer) })
watch(user, (u) => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen bg-white text-gray-900">
    <div class="max-w-4xl mx-auto px-6 py-6 space-y-6">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-lg font-medium text-gray-900" style="font-family:'Fraunces',serif;">Waves</h1>
          <p class="text-xs text-gray-400 mt-0.5 tracking-wide">Release review gate · upcoming waves · merge timeline</p>
        </div>
        <button @click="loadAll" class="px-3 py-1.5 bg-gray-50 text-gray-600 text-xs rounded border border-gray-200 hover:text-gray-900 transition-colors">↻</button>
      </div>

      <div v-if="error" class="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">{{ error }}</div>
      <div v-if="loading && !data" class="text-center py-12 text-gray-400 text-sm">Loading waves…</div>

      <!-- Pending release approval cards (the staging→prod gate) -->
      <section v-if="data">
        <h2 class="text-xs font-medium text-gray-500 tracking-[0.15em] uppercase mb-2">Release gate — pending approval</h2>
        <div v-if="!data.pending_release_cards?.length" class="text-xs text-gray-400 border border-gray-200 rounded-lg px-4 py-5 text-center">
          No staging batches are waiting on operator approval.
        </div>
        <div v-else class="space-y-4">
          <div v-for="c in data.pending_release_cards" :key="c.id" class="bg-white border border-gray-200 border-l-2 border-l-emerald-400 rounded-lg overflow-hidden">
            <div class="px-5 py-3 border-b border-gray-200 flex items-center justify-between gap-3">
              <div class="flex items-center gap-2">
                <span class="text-[10px] px-2 py-0.5 rounded border bg-emerald-50 text-emerald-600 border-emerald-200 font-medium tracking-wider">RELEASE</span>
                <span class="text-[10px] text-gray-500 bg-gray-50 px-2 py-0.5 rounded border border-gray-200">{{ c.project }}</span>
              </div>
              <span class="text-[10px] text-gray-400 font-mono">{{ c.created_at ? ago(c.created_at) : '' }}</span>
            </div>
            <div class="px-5 pt-3 pb-2">
              <h3 class="text-sm font-medium text-gray-900" style="font-family:'Fraunces',serif;">{{ c.title }}</h3>
              <p class="text-xs text-gray-500 mt-1">{{ c.why }}</p>
            </div>
            <div v-if="c.brief_json?.included?.length" class="px-5 pb-2">
              <div class="rounded border border-gray-200 overflow-hidden">
                <div class="px-3 py-1 bg-gray-50 border-b border-gray-200"><span class="text-[9px] font-medium text-gray-500 tracking-[0.15em] uppercase">Included work · {{ c.brief_json.ahead }} changes → {{ c.brief_json.prod_branch }}</span></div>
                <div class="px-3 py-2 text-[11px] text-gray-600 font-mono leading-relaxed max-h-40 overflow-y-auto whitespace-pre-line">{{ c.brief_json.included.join('\n') }}</div>
              </div>
            </div>
            <div v-if="c.brief_json?.qa" class="px-5 pb-3 text-[11px] text-gray-500">QA: {{ c.brief_json.qa }} · staging <span class="font-mono">{{ (c.brief_json.staging_sha || '').slice(0, 10) }}</span></div>
            <div class="px-5 py-3 border-t border-gray-200 flex gap-3">
              <button @click="decide(c, 'approved')" :disabled="deciding === c.id"
                class="px-6 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded border border-emerald-600 transition-colors disabled:opacity-40">
                Approve release
              </button>
              <button @click="decide(c, 'denied')" :disabled="deciding === c.id"
                class="px-6 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-medium rounded border border-red-600 transition-colors disabled:opacity-40">
                Hold / deny
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- Running now -->
      <section v-if="data && runningProjects.length">
        <h2 class="text-xs font-medium text-gray-500 tracking-[0.15em] uppercase mb-2">Running now</h2>
        <div class="space-y-2">
          <div v-for="p in runningProjects" :key="p" class="border border-gray-200 rounded-lg px-4 py-2.5">
            <div class="text-xs font-medium text-gray-700 mb-1">{{ p }} <span class="text-gray-400 font-normal">· {{ data.running[p].length }} running</span></div>
            <div v-for="t in data.running[p].slice(0, 8)" :key="t.id" class="text-[11px] text-gray-500 font-mono truncate">{{ t.slug }}</div>
          </div>
        </div>
      </section>

      <!-- Upcoming waves -->
      <section v-if="data">
        <h2 class="text-xs font-medium text-gray-500 tracking-[0.15em] uppercase mb-2">Upcoming waves</h2>
        <div v-if="!upcomingProjects.length" class="text-xs text-gray-400 border border-gray-200 rounded-lg px-4 py-5 text-center">Queue is empty.</div>
        <div v-else class="space-y-2">
          <div v-for="p in upcomingProjects" :key="p" class="border border-gray-200 rounded-lg px-4 py-2.5">
            <div class="text-xs font-medium text-gray-700 mb-1.5">{{ p }} <span class="text-gray-400 font-normal">· {{ data.upcoming[p].length }} queued</span></div>
            <div v-for="t in data.upcoming[p].slice(0, 10)" :key="t.id" class="flex items-baseline gap-2 py-0.5">
              <span class="text-[10px] text-gray-400 font-mono flex-shrink-0">{{ t.state }}</span>
              <span class="text-[11px] text-gray-600 truncate">{{ t.summary || t.slug }}</span>
              <span v-if="t.submitted_by" class="text-[10px] text-emerald-600 flex-shrink-0">{{ t.submitted_by }}</span>
            </div>
            <div v-if="data.upcoming[p].length > 10" class="text-[10px] text-gray-400 mt-1">+ {{ data.upcoming[p].length - 10 }} more</div>
          </div>
        </div>
      </section>

      <!-- Recent releases -->
      <section v-if="data?.recent_releases?.length">
        <h2 class="text-xs font-medium text-gray-500 tracking-[0.15em] uppercase mb-2">Recent releases</h2>
        <div class="border border-gray-200 rounded-lg divide-y divide-gray-100">
          <div v-for="(r, i) in data.recent_releases" :key="i" class="px-4 py-2 flex items-center gap-3">
            <span class="text-[11px] text-gray-700 font-medium w-28 truncate">{{ r.project }}</span>
            <span class="text-[10px] px-2 py-0.5 rounded border"
              :class="r.deploy_status === 'ok' || r.deploy_status === 'verified' ? 'bg-emerald-50 text-emerald-600 border-emerald-200' : r.deploy_status === 'failed' ? 'bg-red-50 text-red-600 border-red-200' : 'bg-amber-50 text-amber-600 border-amber-200'">
              {{ r.deploy_status }}
            </span>
            <span class="text-[11px] text-gray-500">{{ r.n_changes }} changes</span>
            <span class="text-[10px] text-gray-400 font-mono ml-auto">{{ r.created_at ? ago(r.created_at) : '' }}</span>
          </div>
        </div>
      </section>

      <!-- Steering history -->
      <section v-if="data?.recent_steering?.length">
        <h2 class="text-xs font-medium text-gray-500 tracking-[0.15em] uppercase mb-2">Steering history</h2>
        <div class="border border-gray-200 rounded-lg divide-y divide-gray-100">
          <div v-for="s in data.recent_steering" :key="s.id" class="px-4 py-2">
            <div class="flex items-center gap-2">
              <span class="text-[10px] px-2 py-0.5 rounded border bg-gray-50 text-gray-600 border-gray-200 font-mono">{{ s.event_type }}</span>
              <span v-if="s.project" class="text-[11px] text-gray-500">{{ s.project }}</span>
              <span v-if="s.actor_label" class="text-[11px] text-emerald-600">{{ s.actor_label }}</span>
              <span class="text-[10px] text-gray-400 font-mono ml-auto">{{ s.created_at ? ago(s.created_at) : '' }}</span>
            </div>
            <div v-if="s.rationale" class="text-[11px] text-gray-500 mt-1 italic">{{ s.rationale }}</div>
          </div>
        </div>
      </section>

    </div>
  </div>
</template>

<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// MissionControl — full-bleed live status band for the top of the dashboard.
// Linear/Vercel-grade: tabular-figure numerics, the existing live-dot + StatusPill,
// a calm real-time feel. Token-driven (tailwind.config.js) — no hardcoded hex.
//
// Pure presentational: the parent owns the data model and passes already-loaded
// rows (tasks/runners/approvals/outcomes). Reuses the same shapes index.vue holds.
// ─────────────────────────────────────────────────────────────────────────────
import StatusPill from './StatusPill.vue'

const props = defineProps<{
  tasks: any[]
  runners: any[]
  approvals: any[]
  outcomes: any[]
  spend: number
  /** epoch ms of the last realtime event the parent observed; optional. */
  lastEventAt?: number | null
}>()

// Match the canonical state→tone map used in index.vue (single source of truth
// would ideally be exported; mirrored here to keep the component self-contained).
const STATE_TONE: Record<string, string> = {
  RUNNING: 'bg-status-running/20 text-blue-300',
  DONE: 'bg-status-done/20 text-green-300',
  MERGED: 'bg-status-done/20 text-green-300',
  QUEUED: 'bg-status-queued/20 text-slate-300',
  WAITING: 'bg-status-queued/20 text-slate-300',
  RETRY: 'bg-status-retry/20 text-amber-300',
  BLOCKED: 'bg-status-blocked/20 text-red-300',
  CONFLICT: 'bg-status-blocked/20 text-red-300',
  TESTFAIL: 'bg-status-blocked/20 text-red-300',
}
function toneFor(state: string) {
  return STATE_TONE[state] || 'bg-surface-raised text-slate-300'
}

function aliveRunner(r: any) {
  return r?.last_seen && (Date.now() - new Date(r.last_seen).getTime()) < 60_000
}

// ── derived live metrics ────────────────────────────────────────────────────
const liveRunners = computed(() => props.runners.filter(aliveRunner))
const anyAlive = computed(() => liveRunners.value.length > 0)

const activeRuns = computed(() =>
  props.tasks.filter(t => t.state === 'RUNNING').length
)

// status mix across all tasks, ordered for a stable, readable strip
const STATE_ORDER = ['RUNNING', 'QUEUED', 'WAITING', 'RETRY', 'BLOCKED', 'DONE', 'MERGED'] as const
const statusMix = computed(() => {
  const counts: Record<string, number> = {}
  for (const t of props.tasks) {
    const s = (t.state || 'UNKNOWN').toUpperCase()
    counts[s] = (counts[s] || 0) + 1
  }
  const ordered = STATE_ORDER
    .filter(s => counts[s])
    .map(s => ({ state: s, count: counts[s] }))
  // append any non-canonical states at the end so nothing is silently dropped
  for (const [s, n] of Object.entries(counts)) {
    if (!STATE_ORDER.includes(s as any)) ordered.push({ state: s, count: n })
  }
  return ordered
})
const blockedCount = computed(() =>
  props.tasks.filter(t => ['BLOCKED', 'CONFLICT', 'TESTFAIL'].includes(t.state)).length
)

// throughput: outcomes integrated in the last 24h + their spend
const throughput = computed(() => {
  const cutoff = Date.now() - 24 * 60 * 60_000
  let merged = 0
  let recentSpend = 0
  for (const o of props.outcomes) {
    const t = o.created_at ? new Date(o.created_at).getTime() : 0
    if (t >= cutoff) {
      if (o.integrated) merged++
      recentSpend += Number(o.usd || 0)
    }
  }
  return { merged, recentSpend }
})

// last-event freshness — prefers the parent's realtime timestamp, else newest task
const lastEvent = computed(() => {
  if (props.lastEventAt) return props.lastEventAt
  let newest = 0
  for (const t of props.tasks) {
    const ts = t.updated_at || t.created_at
    const ms = ts ? new Date(ts).getTime() : 0
    if (ms > newest) newest = ms
  }
  for (const r of props.runners) {
    const ms = r.last_seen ? new Date(r.last_seen).getTime() : 0
    if (ms > newest) newest = ms
  }
  return newest || null
})

// re-render the relative clock every 15s without forcing a parent reload
const nowTick = ref(Date.now())
let clockTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => { clockTimer = setInterval(() => { nowTick.value = Date.now() }, 15_000) })
onBeforeUnmount(() => { if (clockTimer) clearInterval(clockTimer) })

function relTime(ms: number | null) {
  if (!ms) return '—'
  void nowTick.value // reactive dependency so this recomputes on tick
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000))
  if (s < 10) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.round(h / 24)}d ago`
}
function fmtUsd(n: number) {
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// "live" only if there's an alive runner AND an event in the last 2 min
const isLive = computed(() => {
  if (!anyAlive.value) return false
  const le = lastEvent.value
  return le ? (Date.now() - le < 120_000) : true
})
</script>

<template>
  <!-- full-bleed band: parent uses -mx-5 px-5 so it spans edge-to-edge -->
  <section
    aria-label="Mission control — live system status"
    class="relative -mx-5 px-5 py-4 mb-6 border-y border-border-subtle
           bg-gradient-to-b from-surface/90 to-canvas/60 backdrop-blur-sm"
  >
    <!-- top row: live state + clock -->
    <div class="flex items-center gap-2.5 mb-3">
      <span class="relative flex w-2 h-2" role="img"
            :aria-label="isLive ? 'Live — runners active' : 'Idle — no active runners'">
        <span v-if="isLive"
              class="motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full opacity-60 bg-status-done"></span>
        <span class="relative inline-flex w-2 h-2 rounded-full"
              :class="isLive ? 'bg-status-done dot-breathe' : 'bg-status-blocked'"></span>
      </span>
      <span class="text-[11px] font-semibold uppercase tracking-[0.14em]"
            :class="isLive ? 'text-green-300' : 'text-slate-500'">
        {{ isLive ? 'Live' : 'Idle' }}
      </span>
      <span class="text-slate-600">·</span>
      <span class="text-[11px] text-slate-500">Mission Control</span>
      <span class="flex-1"></span>
      <span class="text-[11px] text-slate-500">
        Last event
        <time class="font-mono tabular-nums text-slate-400 ml-1">{{ relTime(lastEvent) }}</time>
      </span>
    </div>

    <!-- tiles -->
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">

      <!-- active runs -->
      <div class="rounded-xl border border-border-subtle bg-surface/70 px-3.5 py-3">
        <div class="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Active runs</div>
        <div class="flex items-baseline gap-2">
          <span class="text-2xl font-semibold font-mono tabular-nums leading-none"
                :class="activeRuns ? 'text-blue-300' : 'text-slate-300'">{{ activeRuns }}</span>
          <span class="text-[11px] text-slate-500 font-mono tabular-nums">/ {{ tasks.length }} total</span>
        </div>
      </div>

      <!-- runner fleet -->
      <div class="rounded-xl border border-border-subtle bg-surface/70 px-3.5 py-3">
        <div class="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Runners</div>
        <div class="flex items-baseline gap-2">
          <span class="text-2xl font-semibold font-mono tabular-nums leading-none"
                :class="anyAlive ? 'text-green-300' : 'text-red-300'">{{ liveRunners.length }}</span>
          <span class="text-[11px] text-slate-500 font-mono tabular-nums">/ {{ runners.length }} known</span>
        </div>
      </div>

      <!-- status mix (spans 2 cols on wider screens) -->
      <div class="rounded-xl border border-border-subtle bg-surface/70 px-3.5 py-3
                  col-span-2 lg:col-span-1">
        <div class="flex items-center gap-2 mb-1.5">
          <span class="text-[10px] uppercase tracking-wider text-slate-500">Status mix</span>
          <span v-if="blockedCount"
                class="text-[10px] font-bold text-red-300">⚠ {{ blockedCount }} blocked</span>
        </div>
        <div v-if="statusMix.length" class="flex flex-wrap gap-1">
          <StatusPill
            v-for="s in statusMix" :key="s.state"
            :label="`${s.state} ${s.count}`"
            :tone="toneFor(s.state)" />
        </div>
        <div v-else class="text-[11px] text-slate-600 italic">No tasks</div>
      </div>

      <!-- cost / throughput -->
      <div class="rounded-xl border border-border-subtle bg-surface/70 px-3.5 py-3">
        <div class="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Spend · 24h merged</div>
        <div class="flex items-baseline gap-2">
          <span class="text-2xl font-semibold font-mono tabular-nums leading-none text-slate-200">
            ${{ fmtUsd(spend) }}
          </span>
        </div>
        <div class="text-[11px] text-slate-500 font-mono tabular-nums mt-1">
          {{ throughput.merged }} merged · ${{ fmtUsd(throughput.recentSpend) }} /24h
        </div>
      </div>

      <!-- approvals waiting -->
      <div class="rounded-xl border px-3.5 py-3"
           :class="approvals.length
             ? 'border-amber-600/50 bg-status-retry/10'
             : 'border-border-subtle bg-surface/70'">
        <div class="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Awaiting approval</div>
        <div class="flex items-baseline gap-2">
          <span class="text-2xl font-semibold font-mono tabular-nums leading-none"
                :class="approvals.length ? 'text-amber-300' : 'text-slate-300'">{{ approvals.length }}</span>
          <span v-if="approvals.length" class="text-[11px] text-amber-300/80">needs you</span>
          <span v-else class="text-[11px] text-slate-500">all clear</span>
        </div>
      </div>

    </div>
  </section>
</template>

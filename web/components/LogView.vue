<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// LogView — a proper log surface for the orchestrator.
//
//  • JetBrains Mono (font-mono token) with tabular numerics for aligned timestamps
//  • per-line level styling — level is conveyed by an ICON + TEXT label, never by
//    colour alone (WCAG 1.4.1: don't use colour as the only visual means)
//  • copy-one-line and copy-all affordances
//  • "follow tail" toggle — auto-scrolls to newest; auto-pauses when the user
//    scrolls up, resumes when they return to the bottom
//  • reusable: bind a live stream via the `lines` prop, or let it render sample
//    lines so the surface is demoable before the real source is wired.
//
// TODO(bind-stream): the orchestrator currently exposes task progress via
// `tasks[].log_tail` (a raw text blob) and Supabase realtime on the `tasks`
// table. To bind the real stream, parse `log_tail` into LogLine[] (one entry per
// text line, infer level from a leading token) and pass it in as `:lines`, or add
// a dedicated `run_logs` table + realtime channel and map rows → LogLine.
// ─────────────────────────────────────────────────────────────────────────────

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export interface LogLine {
  /** epoch ms or ISO string; rendered as HH:MM:SS. Optional. */
  ts?: number | string
  level: LogLevel
  /** the message body (already plain text). */
  message: string
  /** optional source tag, e.g. runner id / task slug. */
  source?: string
}

const props = withDefaults(defineProps<{
  lines?: LogLine[]
  title?: string
  /** max rows kept in the DOM; older lines are virtually dropped from view. */
  maxLines?: number
  /** start with tail-follow on. */
  followByDefault?: boolean
  height?: string
}>(), {
  title: 'Logs',
  maxLines: 500,
  followByDefault: true,
  height: '20rem',
})

// ── sample data (used when no `lines` are bound) ─────────────────────────────
const SAMPLE: LogLine[] = [
  { ts: Date.now() - 8200, level: 'info',  source: 'runner-a1', message: 'claimed task build/auth-refactor (kind=build)' },
  { ts: Date.now() - 7600, level: 'debug', source: 'runner-a1', message: 'spawned claude-sonnet · ctx 18.4k tok · cache hit 71%' },
  { ts: Date.now() - 6400, level: 'info',  source: 'runner-a1', message: 'edit app/api/session.ts (+42 −6)  ·  3 files touched' },
  { ts: Date.now() - 5200, level: 'warn',  source: 'runner-a1', message: 'eslint: 2 warnings (no-unused-vars) — non-blocking' },
  { ts: Date.now() - 4100, level: 'info',  source: 'runner-a1', message: 'tests: 48 passed, 0 failed in 12.3s' },
  { ts: Date.now() - 2900, level: 'error', source: 'runner-b2', message: 'rate_limit: anthropic 429 — backing off 30s (attempt 2/5)' },
  { ts: Date.now() - 1500, level: 'info',  source: 'runner-a1', message: 'opened PR #318 · confidence 0.86 · $0.42' },
  { ts: Date.now() - 400,  level: 'debug', source: 'runner-a1', message: 'heartbeat ok · active_tasks=1 · disk 63%' },
]

const data = computed<LogLine[]>(() => {
  const src = (props.lines && props.lines.length) ? props.lines : SAMPLE
  // keep only the most recent maxLines for DOM health
  return src.length > props.maxLines ? src.slice(src.length - props.maxLines) : src
})
const usingSample = computed(() => !(props.lines && props.lines.length))

// ── level presentation: icon + text + token-driven colour (colour is redundant) ─
const LEVEL_META: Record<LogLevel, { icon: string; label: string; text: string; chip: string }> = {
  debug: { icon: '◍', label: 'DEBUG', text: 'text-slate-500', chip: 'bg-surface-raised text-slate-400' },
  info:  { icon: '›', label: 'INFO',  text: 'text-slate-300', chip: 'bg-status-running/20 text-blue-300' },
  warn:  { icon: '▲', label: 'WARN',  text: 'text-amber-200', chip: 'bg-status-retry/20 text-amber-300' },
  error: { icon: '✕', label: 'ERROR', text: 'text-red-200',   chip: 'bg-status-blocked/20 text-red-300' },
}

function fmtTs(ts?: number | string) {
  if (ts == null) return '--:--:--'
  const d = typeof ts === 'number' ? new Date(ts) : new Date(ts)
  if (isNaN(d.getTime())) return '--:--:--'
  return d.toLocaleTimeString('en-GB', { hour12: false }) // HH:MM:SS, stable width
}

// ── tail-follow with scroll-aware pause ──────────────────────────────────────
const follow = ref(props.followByDefault)
const scrollEl = ref<HTMLElement | null>(null)

function atBottom() {
  const el = scrollEl.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 24
}
function scrollToBottom() {
  const el = scrollEl.value
  if (el) el.scrollTop = el.scrollHeight
}
function onScroll() {
  // user scrolled up → pause follow; user returned to bottom → resume
  if (!atBottom()) {
    if (follow.value) follow.value = false
  } else if (!follow.value) {
    follow.value = true
  }
}
function toggleFollow() {
  follow.value = !follow.value
  if (follow.value) nextTick(scrollToBottom)
}

watch(() => data.value.length, () => {
  if (follow.value) nextTick(scrollToBottom)
})
onMounted(() => { if (follow.value) nextTick(scrollToBottom) })

// ── copy affordances ─────────────────────────────────────────────────────────
const copiedKey = ref<string | null>(null)
async function copy(text: string, key: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedKey.value = key
    setTimeout(() => { if (copiedKey.value === key) copiedKey.value = null }, 1200)
  } catch { /* clipboard unavailable (e.g. insecure context) — fail silently */ }
}
function lineText(l: LogLine) {
  return `${fmtTs(l.ts)} ${LEVEL_META[l.level].label}${l.source ? ' [' + l.source + ']' : ''} ${l.message}`
}
function copyAll() {
  copy(data.value.map(lineText).join('\n'), '__all__')
}
</script>

<template>
  <section class="bg-surface border border-border-subtle rounded-xl overflow-hidden">
    <!-- header / controls -->
    <header class="flex items-center gap-2 px-3 py-2 border-b border-border-subtle bg-surface-raised/40">
      <h3 class="text-xs uppercase tracking-wider text-slate-400 font-semibold">{{ title }}</h3>
      <span v-if="usingSample"
            class="text-[10px] font-mono text-slate-500 bg-surface-raised rounded px-1.5 py-0.5">
        sample · stream not bound
      </span>
      <span class="flex-1"></span>

      <!-- follow-tail toggle -->
      <button type="button" @click="toggleFollow"
              :aria-pressed="follow"
              class="group flex items-center gap-1.5 text-[11px] rounded-md px-2 py-1 transition-colors"
              :class="follow
                ? 'bg-status-running/20 text-blue-300'
                : 'bg-surface-raised text-slate-400 hover:text-slate-200'">
        <span class="relative flex w-1.5 h-1.5">
          <span v-if="follow"
                class="motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-60"></span>
          <span class="relative inline-flex w-1.5 h-1.5 rounded-full"
                :class="follow ? 'bg-blue-400 dot-breathe' : 'bg-slate-500'"></span>
        </span>
        {{ follow ? 'Following tail' : 'Paused' }}
      </button>

      <!-- copy all -->
      <button type="button" @click="copyAll"
              aria-label="Copy all log lines"
              class="text-[11px] rounded-md px-2 py-1 bg-surface-raised text-slate-400 hover:text-slate-200 transition-colors">
        {{ copiedKey === '__all__' ? '✓ Copied' : 'Copy all' }}
      </button>
    </header>

    <!-- log surface -->
    <div ref="scrollEl" @scroll="onScroll"
         role="log" aria-live="polite" aria-relevant="additions"
         class="overflow-auto font-mono text-xs leading-relaxed bg-canvas/60"
         :style="{ height }">
      <ol class="min-w-full">
        <li v-for="(l, i) in data" :key="i"
            class="group flex items-start gap-2 px-3 py-0.5 border-l-2 hover:bg-surface-raised/30"
            :class="{
              'border-transparent': l.level === 'info' || l.level === 'debug',
              'border-status-retry/60': l.level === 'warn',
              'border-status-blocked/70': l.level === 'error',
            }">
          <!-- timestamp (tabular for alignment) -->
          <time class="tabular-nums text-slate-600 select-none whitespace-nowrap">{{ fmtTs(l.ts) }}</time>

          <!-- level: ICON + LABEL (not colour alone) -->
          <span class="inline-flex items-center gap-1 rounded px-1 text-[10px] font-semibold whitespace-nowrap select-none"
                :class="LEVEL_META[l.level].chip"
                :aria-label="LEVEL_META[l.level].label + ' level'">
            <span aria-hidden="true">{{ LEVEL_META[l.level].icon }}</span>{{ LEVEL_META[l.level].label }}
          </span>

          <!-- source tag -->
          <span v-if="l.source" class="text-slate-500 whitespace-nowrap select-none">[{{ l.source }}]</span>

          <!-- message -->
          <span class="flex-1 break-words" :class="LEVEL_META[l.level].text">{{ l.message }}</span>

          <!-- per-line copy (appears on hover/focus) -->
          <button type="button"
                  @click="copy(lineText(l), 'l' + i)"
                  :aria-label="'Copy log line ' + (i + 1)"
                  class="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity
                         text-[10px] text-slate-500 hover:text-slate-200 select-none whitespace-nowrap">
            {{ copiedKey === 'l' + i ? '✓' : 'copy' }}
          </button>
        </li>
      </ol>
    </div>
  </section>
</template>

<script setup lang="ts">
// Config-change monitoring dashboard.
//
// The config request/approval API (requests.get, :id/approve, :id/reject, :id/approvals)
// shipped without any surface rendering it — nothing under web/pages or web/components
// referenced /api/config at all, so pending config changes were invisible unless someone
// queried Supabase by hand. This is that surface: pending approvals, synchronized state,
// and read errors, refreshed on an interval.
definePageMeta({ layout: 'default' })

interface Summary {
  generatedAt: string
  counts: { pending: number; approved: number; rejected: number; other: number }
  total: number
  stalePending: number
  stalePendingIds: string[]
  pending: any[]
  recent: any[]
  decisions: any[]
  errors: string[]
}

const summary = ref<Summary | null>(null)
const loading = ref(false)
const error = ref('')
const lastUpdated = ref<string>('')

const REFRESH_MS = 15_000
let timer: ReturnType<typeof setInterval> | null = null

async function load(showSpinner = false) {
  if (showSpinner) loading.value = true
  try {
    summary.value = await $fetch<Summary>('/api/config/summary')
    error.value = ''
    lastUpdated.value = new Date().toLocaleTimeString()
  } catch (cause: any) {
    error.value = cause?.data?.message || cause?.message || 'Could not load config summary.'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load(true)
  timer = setInterval(() => load(false), REFRESH_MS)
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })

function relAge(ms: number): string {
  const mins = Math.floor(ms / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 48) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

function statusClass(status: string): string {
  if (status === 'approved') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (status === 'rejected') return 'bg-red-50 text-red-700 border-red-200'
  if (status === 'pending') return 'bg-amber-50 text-amber-700 border-amber-200'
  return 'bg-gray-50 text-gray-600 border-gray-200'
}

const isStale = (id: string) => Boolean(summary.value?.stalePendingIds?.includes(id))
</script>

<template>
  <div class="min-h-full bg-gray-50">
    <header class="border-b bg-white px-6 py-5">
      <div class="flex items-start justify-between gap-4">
        <div>
          <div class="text-[10px] font-semibold uppercase tracking-[.16em] text-blue-600">Configuration</div>
          <h1 class="mt-1 text-2xl font-semibold">Config change monitor</h1>
          <p class="mt-2 text-sm text-gray-500">
            Pending approvals, synchronized state, and read errors across fleet configuration requests.
          </p>
        </div>
        <div class="text-right">
          <button
            class="rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-gray-50"
            :disabled="loading"
            @click="load(true)"
          >
            {{ loading ? 'Refreshing…' : 'Refresh' }}
          </button>
          <div v-if="lastUpdated" class="mt-1 text-[10px] text-gray-400">
            Updated {{ lastUpdated }} · auto every {{ REFRESH_MS / 1000 }}s
          </div>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-6xl space-y-6 p-6">
      <div v-if="error" class="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
        {{ error }}
      </div>

      <div
        v-if="summary?.errors?.length"
        class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
      >
        <div class="font-medium">Partial read</div>
        <ul class="mt-1 list-disc space-y-0.5 pl-4 text-xs">
          <li v-for="e in summary.errors" :key="e">{{ e }}</li>
        </ul>
      </div>

      <section v-if="summary" class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div
          v-for="m in [
            { l: 'Pending', v: summary.counts.pending, accent: 'text-amber-600' },
            { l: 'Approved', v: summary.counts.approved, accent: 'text-emerald-600' },
            { l: 'Rejected', v: summary.counts.rejected, accent: 'text-red-600' },
            { l: 'Waiting >24h', v: summary.stalePending, accent: 'text-orange-600' },
          ]"
          :key="m.l"
          class="rounded-xl border bg-white p-4"
        >
          <div class="text-[10px] uppercase tracking-wide text-gray-400">{{ m.l }}</div>
          <div class="mt-1 text-2xl font-semibold" :class="m.accent">{{ m.v }}</div>
        </div>
      </section>

      <section class="rounded-xl border bg-white">
        <h2 class="border-b px-5 py-3 text-sm font-semibold">Pending approval</h2>
        <div v-if="!summary?.pending?.length" class="p-8 text-center text-xs text-gray-500">
          Nothing is waiting on a decision.
        </div>
        <table v-else class="w-full text-left text-xs">
          <thead class="text-[10px] uppercase tracking-wide text-gray-400">
            <tr>
              <th class="px-5 py-2 font-medium">Key</th>
              <th class="px-5 py-2 font-medium">Value</th>
              <th class="px-5 py-2 font-medium">Requester</th>
              <th class="px-5 py-2 font-medium">Waiting</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in summary.pending" :key="r.id" class="border-t">
              <td class="px-5 py-2.5 font-mono">{{ r.key }}</td>
              <td class="max-w-xs truncate px-5 py-2.5 font-mono text-gray-500">{{ r.value }}</td>
              <td class="px-5 py-2.5 text-gray-600">{{ r.requester }}</td>
              <td class="px-5 py-2.5">
                <span :class="isStale(r.id) ? 'font-semibold text-orange-600' : 'text-gray-500'">
                  {{ relAge(r.ageMs) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="rounded-xl border bg-white">
        <h2 class="border-b px-5 py-3 text-sm font-semibold">Recent changes</h2>
        <div v-if="!summary?.recent?.length" class="p-8 text-center text-xs text-gray-500">
          No configuration requests recorded yet.
        </div>
        <table v-else class="w-full text-left text-xs">
          <thead class="text-[10px] uppercase tracking-wide text-gray-400">
            <tr>
              <th class="px-5 py-2 font-medium">Key</th>
              <th class="px-5 py-2 font-medium">Status</th>
              <th class="px-5 py-2 font-medium">Requester</th>
              <th class="px-5 py-2 font-medium">Last decision</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in summary.recent" :key="r.id" class="border-t">
              <td class="px-5 py-2.5 font-mono">{{ r.key }}</td>
              <td class="px-5 py-2.5">
                <span class="rounded-full border px-2 py-0.5 text-[10px] font-medium" :class="statusClass(r.status)">
                  {{ r.status }}
                </span>
              </td>
              <td class="px-5 py-2.5 text-gray-600">{{ r.requester }}</td>
              <td class="px-5 py-2.5 text-gray-500">
                <span v-if="r.lastDecision">{{ r.lastDecision.approver }} · {{ r.lastDecision.decision }}</span>
                <span v-else class="text-gray-300">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </main>
  </div>
</template>

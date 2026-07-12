<template>
  <div class="p-6 max-w-6xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold text-gray-100">Shadow Decisions</h1>
        <p class="text-sm text-gray-500 mt-1">Calibration mode &mdash; compare AI policy decisions against human outcomes</p>
      </div>
      <button
        class="px-3 py-1.5 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700 transition-colors"
        @click="refresh"
      >
        Refresh
      </button>
    </div>

    <!-- Calibration dashboard -->
    <div class="grid grid-cols-4 gap-4 mb-8">
      <!-- Alignment gauge -->
      <div class="col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-6 flex items-center gap-6">
        <div class="text-center">
          <div
            class="text-5xl font-bold"
            :class="alignmentColor"
          >
            {{ (calibration.alignmentRate * 100).toFixed(1) }}%
          </div>
          <div class="text-xs text-gray-500 mt-1 uppercase tracking-wider">Alignment Rate</div>
        </div>
        <div class="flex-1 space-y-2">
          <!-- Progress bar -->
          <div class="w-full bg-gray-800 rounded-full h-3 overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-500"
              :class="calibration.alignmentRate > 0.95 ? 'bg-green-500' : calibration.alignmentRate > 0.8 ? 'bg-amber-500' : 'bg-red-500'"
              :style="{ width: `${calibration.alignmentRate * 100}%` }"
            />
          </div>
          <div class="flex justify-between text-xs text-gray-600">
            <span>0%</span>
            <span class="text-amber-600">|95% threshold|</span>
            <span>100%</span>
          </div>
        </div>
      </div>

      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">Total Shadow</div>
        <div class="text-2xl font-bold text-gray-100 mt-1">{{ calibration.totalShadow }}</div>
        <div class="text-xs text-gray-600 mt-1">{{ calibration.humanDecided }} human-decided</div>
      </div>

      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">False Approves</div>
        <div class="text-2xl font-bold text-red-400 mt-1">{{ calibration.falseApproves }}</div>
        <div class="text-xs text-gray-600 mt-1">{{ calibration.falseEscalates }} false escalates</div>
      </div>
    </div>

    <!-- Ready to promote banner -->
    <div
      v-if="calibration.readyToPromote"
      class="mb-6 bg-green-950/50 border border-green-800 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-green-400 text-lg">&#10003;</span>
      <div>
        <div class="text-sm font-medium text-green-300">Ready to Promote</div>
        <div class="text-xs text-green-600">Alignment rate exceeds 95% with 50+ human decisions. Shadow policies can go live.</div>
      </div>
    </div>

    <!-- Two-column layout: buckets + promotion candidates -->
    <div class="grid grid-cols-2 gap-6 mb-8">
      <!-- Confidence buckets -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-800">
          <h2 class="text-sm font-semibold text-gray-300">Confidence Breakdown</h2>
        </div>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-xs text-gray-500 uppercase">
              <th class="text-left px-4 py-2">Bucket</th>
              <th class="text-right px-4 py-2">Count</th>
              <th class="text-right px-4 py-2">Alignment</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="bucket in calibration.confidenceByBucket"
              :key="bucket.bucket"
              class="border-t border-gray-800/50"
            >
              <td class="px-4 py-2.5 font-mono text-gray-300">{{ bucket.bucket }}</td>
              <td class="px-4 py-2.5 text-right text-gray-400">{{ bucket.count }}</td>
              <td class="px-4 py-2.5 text-right">
                <span
                  :class="bucket.alignmentRate > 0.95 ? 'text-green-400' : bucket.alignmentRate > 0.8 ? 'text-amber-400' : 'text-red-400'"
                >
                  {{ (bucket.alignmentRate * 100).toFixed(0) }}%
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Promotion candidates -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-800">
          <h2 class="text-sm font-semibold text-gray-300">Promotion Candidates</h2>
        </div>
        <div v-if="promotionCandidates.length === 0" class="px-4 py-6 text-center text-gray-600 text-sm">
          No policies ready for promotion yet.<br>
          <span class="text-xs">Need &gt;95% alignment and &gt;50 decisions.</span>
        </div>
        <div v-else class="divide-y divide-gray-800/50">
          <div
            v-for="candidate in promotionCandidates"
            :key="candidate.policyId"
            class="px-4 py-3 flex items-center justify-between"
          >
            <div>
              <span class="text-sm font-mono text-gray-300">{{ candidate.policyId }}</span>
              <span class="text-xs text-gray-600 ml-2">{{ candidate.count }} decisions</span>
            </div>
            <span class="text-xs px-2 py-0.5 rounded-full bg-green-950 text-green-400 border border-green-800">
              {{ (candidate.alignmentRate * 100).toFixed(1) }}%
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Recent shadow decisions table -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div class="px-4 py-3 border-b border-gray-800">
        <h2 class="text-sm font-semibold text-gray-300">Recent Shadow Decisions</h2>
      </div>

      <div v-if="decisions.length === 0" class="px-4 py-8 text-center text-gray-600 text-sm">
        No shadow decisions recorded yet. Enable shadow mode on policies to begin calibration.
      </div>

      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-xs text-gray-500 uppercase border-b border-gray-800">
            <th class="text-left px-4 py-2">App / Domain</th>
            <th class="text-left px-4 py-2">Policy</th>
            <th class="text-center px-4 py-2">AI Decision</th>
            <th class="text-center px-4 py-2">Human Decision</th>
            <th class="text-center px-4 py-2">Aligned</th>
            <th class="text-right px-4 py-2">Confidence</th>
            <th class="text-right px-4 py-2">Time</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="d in decisions"
            :key="d.id"
            class="border-t border-gray-800/50 hover:bg-gray-800/30 transition-colors"
          >
            <td class="px-4 py-2.5">
              <span class="text-xs font-mono px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">{{ d.app }}</span>
              <span class="text-xs text-gray-500 ml-1.5">{{ d.domain }}</span>
            </td>
            <td class="px-4 py-2.5 text-xs font-mono text-gray-500">{{ d.policyId || '--' }}</td>
            <td class="px-4 py-2.5 text-center">
              <span
                class="text-xs px-2 py-0.5 rounded-full"
                :class="aiDecisionClass(d.aiDecision)"
              >
                {{ d.aiDecision }}
              </span>
            </td>
            <td class="px-4 py-2.5 text-center">
              <span
                v-if="d.humanDecision"
                class="text-xs px-2 py-0.5 rounded-full"
                :class="humanDecisionClass(d.humanDecision)"
              >
                {{ d.humanDecision }}
              </span>
              <span v-else class="text-xs text-gray-600">pending</span>
            </td>
            <td class="px-4 py-2.5 text-center">
              <span v-if="d.aligned === null" class="text-gray-600">--</span>
              <span v-else-if="d.aligned" class="text-green-400">&#10003;</span>
              <span v-else class="text-red-400">&#10007;</span>
            </td>
            <td class="px-4 py-2.5 text-right">
              <div class="inline-flex items-center gap-1.5">
                <div class="w-12 bg-gray-800 rounded-full h-1.5 overflow-hidden">
                  <div
                    class="h-full rounded-full"
                    :class="d.aiConfidence > 0.8 ? 'bg-indigo-500' : d.aiConfidence > 0.5 ? 'bg-amber-500' : 'bg-red-500'"
                    :style="{ width: `${d.aiConfidence * 100}%` }"
                  />
                </div>
                <span class="text-xs text-gray-500 font-mono">{{ (d.aiConfidence * 100).toFixed(0) }}%</span>
              </div>
            </td>
            <td class="px-4 py-2.5 text-right text-xs text-gray-500">
              {{ formatTime(d.createdAt) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface ShadowDecision {
  id: string
  eventId: string
  app: string
  domain: string
  policyId?: string
  aiDecision: string
  humanDecision?: string
  aligned: boolean | null
  aiConfidence: number
  createdAt: string
  decidedAt?: string
  details: any
}

interface CalibrationReport {
  totalShadow: number
  humanDecided: number
  alignmentRate: number
  falseApproves: number
  falseEscalates: number
  confidenceByBucket: { bucket: string; count: number; alignmentRate: number }[]
  readyToPromote: boolean
}

const decisions = ref<ShadowDecision[]>([])
const calibration = ref<CalibrationReport>({
  totalShadow: 0,
  humanDecided: 0,
  alignmentRate: 0,
  falseApproves: 0,
  falseEscalates: 0,
  confidenceByBucket: [],
  readyToPromote: false,
})
const promotionCandidates = ref<{ policyId: string; count: number; alignmentRate: number }[]>([])

const alignmentColor = computed(() => {
  const rate = calibration.value.alignmentRate
  if (rate > 0.95) return 'text-green-400'
  if (rate > 0.8) return 'text-amber-400'
  return 'text-red-400'
})

async function refresh() {
  try {
    const data = await $fetch<{
      decisions: ShadowDecision[]
      calibration: CalibrationReport
      promotionCandidates: { policyId: string; count: number; alignmentRate: number }[]
    }>('/api/admin/shadow')
    decisions.value = data.decisions
    calibration.value = data.calibration
    promotionCandidates.value = data.promotionCandidates
  } catch {}
}

onMounted(refresh)

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}

function aiDecisionClass(decision: string): string {
  switch (decision) {
    case 'auto_approve': return 'bg-green-950 text-green-400 border border-green-800'
    case 'auto_deny': return 'bg-red-950 text-red-400 border border-red-800'
    case 'escalate': return 'bg-amber-950 text-amber-400 border border-amber-800'
    default: return 'bg-gray-800 text-gray-400'
  }
}

function humanDecisionClass(decision: string): string {
  switch (decision) {
    case 'approved': return 'bg-green-950 text-green-400 border border-green-800'
    case 'denied': return 'bg-red-950 text-red-400 border border-red-800'
    case 'modified': return 'bg-indigo-950 text-indigo-400 border border-indigo-800'
    default: return 'bg-gray-800 text-gray-400'
  }
}
</script>

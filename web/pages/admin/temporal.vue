<template>
  <div class="p-6 max-w-6xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold text-gray-100">Temporal Admin</h1>
        <p class="text-sm text-gray-500 mt-1">Undo chains &mdash; rewind fleet actions within their time window</p>
      </div>
      <button
        class="px-3 py-1.5 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700 transition-colors"
        @click="refresh"
      >
        Refresh
      </button>
    </div>

    <!-- Stats bar -->
    <div class="grid grid-cols-3 gap-4 mb-8">
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">Total Actions</div>
        <div class="text-2xl font-bold text-gray-100 mt-1">{{ history.length }}</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">Undoable Now</div>
        <div class="text-2xl font-bold text-amber-400 mt-1">{{ undoable.length }}</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">Already Undone</div>
        <div class="text-2xl font-bold text-red-400 mt-1">{{ undoneCount }}</div>
      </div>
    </div>

    <!-- Timeline -->
    <div class="relative">
      <!-- Vertical line -->
      <div class="absolute left-4 top-0 bottom-0 w-px bg-gray-800" />

      <div v-for="receipt in history" :key="receipt.id" class="relative pl-10 pb-6">
        <!-- Timeline dot -->
        <div
          class="absolute left-3 top-1.5 w-3 h-3 rounded-full border-2"
          :class="dotClass(receipt)"
        />

        <!-- Chain connector -->
        <div
          v-if="receipt.chainId && isChainStart(receipt)"
          class="absolute left-[18px] top-4 w-3 border-t border-dashed border-indigo-600"
        />

        <!-- Card -->
        <div
          class="bg-gray-900 border rounded-lg p-4 transition-colors"
          :class="receipt.undoneAt ? 'border-red-900/50 opacity-60' : receipt.chainId ? 'border-indigo-900/50' : 'border-gray-800'"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-xs font-mono px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">{{ receipt.app }}</span>
                <span class="text-sm font-medium text-gray-200">{{ receipt.action }}</span>
                <span class="text-xs text-gray-600">&middot;</span>
                <span class="text-xs text-gray-500">{{ receipt.domain }}</span>
                <span
                  v-if="receipt.chainId"
                  class="text-xs px-1.5 py-0.5 rounded bg-indigo-950 text-indigo-400 font-mono"
                >
                  chain:{{ receipt.chainId.slice(0, 8) }}
                </span>
              </div>

              <div class="flex items-center gap-3 mt-2 text-xs text-gray-500">
                <span>{{ formatTime(receipt.executedAt) }}</span>
                <template v-if="receipt.undoneAt">
                  <span class="text-red-500">Undone {{ formatTime(receipt.undoneAt) }} by {{ receipt.undoneBy }}</span>
                </template>
                <template v-else-if="receipt.undoToken">
                  <span :class="isExpired(receipt) ? 'text-gray-600' : 'text-amber-500'">
                    {{ isExpired(receipt) ? 'Window expired' : `Undo in ${countdown(receipt)}` }}
                  </span>
                </template>
                <template v-else>
                  <span class="text-gray-600">No undo available</span>
                </template>
              </div>
            </div>

            <div class="flex items-center gap-2 flex-shrink-0">
              <!-- Undo single -->
              <button
                v-if="canUndo(receipt)"
                class="px-3 py-1 text-xs font-medium bg-red-950 text-red-400 border border-red-900 rounded hover:bg-red-900 transition-colors"
                :disabled="undoing === receipt.id"
                @click="doUndo(receipt.id)"
              >
                {{ undoing === receipt.id ? 'Undoing...' : 'Undo' }}
              </button>

              <!-- Undo chain -->
              <button
                v-if="receipt.chainId && canUndo(receipt) && isChainStart(receipt)"
                class="px-3 py-1 text-xs font-medium bg-indigo-950 text-indigo-400 border border-indigo-900 rounded hover:bg-indigo-900 transition-colors"
                :disabled="undoing === receipt.chainId"
                @click="doUndoChain(receipt.chainId!)"
              >
                {{ undoing === receipt.chainId ? 'Undoing...' : 'Undo Chain' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty state -->
      <div v-if="history.length === 0" class="pl-10 text-gray-600 text-sm py-8">
        No fleet actions recorded yet. Actions with undo tokens will appear here.
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface ActionReceipt {
  id: string
  app: string
  action: string
  domain: string
  payload: any
  undoToken?: string
  undoAction?: string
  executedAt: string
  undoDeadline: string
  undoneAt?: string
  undoneBy?: string
  chainId?: string
}

const history = ref<ActionReceipt[]>([])
const undoable = ref<ActionReceipt[]>([])
const undoing = ref<string | null>(null)

const undoneCount = computed(() => history.value.filter(r => r.undoneAt).length)

async function refresh() {
  try {
    const data = await $fetch<{ history: ActionReceipt[]; undoable: ActionReceipt[] }>('/api/admin/temporal')
    history.value = data.history
    undoable.value = data.undoable
  } catch {}
}

onMounted(() => {
  refresh()
  // Refresh every 10s to update countdowns
  const interval = setInterval(refresh, 10000)
  onUnmounted(() => clearInterval(interval))
})

function canUndo(receipt: ActionReceipt): boolean {
  if (receipt.undoneAt) return false
  if (!receipt.undoToken) return false
  return new Date(receipt.undoDeadline).getTime() > Date.now()
}

function isExpired(receipt: ActionReceipt): boolean {
  return new Date(receipt.undoDeadline).getTime() <= Date.now()
}

function countdown(receipt: ActionReceipt): string {
  const ms = new Date(receipt.undoDeadline).getTime() - Date.now()
  if (ms <= 0) return 'expired'
  const min = Math.floor(ms / 60000)
  const sec = Math.floor((ms % 60000) / 1000)
  return min > 0 ? `${min}m ${sec}s` : `${sec}s`
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function isChainStart(receipt: ActionReceipt): boolean {
  if (!receipt.chainId) return false
  const chainMembers = history.value.filter(r => r.chainId === receipt.chainId)
  return chainMembers[0]?.id === receipt.id
}

function dotClass(receipt: ActionReceipt): string {
  if (receipt.undoneAt) return 'bg-red-500 border-red-700'
  if (receipt.undoToken && !isExpired(receipt)) return 'bg-amber-500 border-amber-700'
  return 'bg-gray-600 border-gray-700'
}

async function doUndo(receiptId: string) {
  undoing.value = receiptId
  try {
    await $fetch('/api/admin/temporal/undo', {
      method: 'POST',
      body: { receiptId, undoneBy: 'operator' },
    })
    await refresh()
  } catch {}
  undoing.value = null
}

async function doUndoChain(chainId: string) {
  undoing.value = chainId
  try {
    await $fetch('/api/admin/temporal/undo-chain', {
      method: 'POST',
      body: { chainId, undoneBy: 'operator' },
    })
    await refresh()
  } catch {}
  undoing.value = null
}
</script>

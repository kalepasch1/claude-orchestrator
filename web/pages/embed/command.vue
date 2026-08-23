<script setup lang="ts">
/**
 * /embed/command — the mountable Madeus surface.
 *
 * A host app on ANOTHER ORIGIN iframes this page, hands it a tenant-scoped
 * embed key, and gets the UniversalCommand outcome box plus the
 * fleet-status/approvals strip. Work initiated here lands in the one fleet.
 *
 * THE ORIGIN RULES, BECAUSE THIS IS A CROSS-ORIGIN SURFACE
 * -------------------------------------------------------
 * 1. We never postMessage to '*'. The host origin is read once from `?host=`
 *    and every reply is addressed to exactly that origin. A wildcard target
 *    would broadcast a tenant's queue to whatever page happens to be listening.
 * 2. Inbound messages are ignored unless event.origin equals that host, and
 *    unless the envelope parses. A message failing either is dropped with a
 *    reason posted back, never acted on.
 * 3. The key is held in memory only — never localStorage, which the embedding
 *    page's other scripts can read.
 */
import {
  EMBED_PROTOCOL_VERSION,
  makeEnvelope,
  parseEnvelope,
  type EmbedSurface,
} from '~/server/utils/embedProtocol'

definePageMeta({ layout: false })

const route = useRoute()

/** The exact origin we will talk to. No default: an unset host means no replies. */
const hostOrigin = computed(() => {
  const raw = String(route.query.host ?? '')
  try {
    return raw ? new URL(raw).origin : ''
  } catch {
    return ''
  }
})
const surface = computed<EmbedSurface>(() =>
  (String(route.query.surface ?? 'universal_command') as EmbedSurface))
const tenantId = ref('')

/** In memory only. Never persisted — the host page can read storage. */
const embedKey = ref('')

const outcome = ref('')
const submitting = ref(false)
const error = ref('')
const lastQueueId = ref('')
const status = ref<{
  runningTasks: number
  queuedTasks: number
  pendingApprovals: Array<{ id: string; summary: string }>
} | null>(null)

function post(kind: string, payload: unknown, correlationId?: string) {
  if (!hostOrigin.value) return
  const env = makeEnvelope('embed_to_host', kind, tenantId.value || 'unknown', surface.value, payload, correlationId)
  window.parent?.postMessage(env, hostOrigin.value)
}

function headers(): Record<string, string> {
  return {
    'content-type': 'application/json',
    'x-madeus-embed-key': embedKey.value,
    'x-madeus-surface': surface.value,
  }
}

async function refreshStatus() {
  if (!embedKey.value) return
  try {
    const res = await $fetch<any>('/api/embed/status', { headers: headers() })
    if (res?.ok) {
      status.value = {
        runningTasks: res.runningTasks,
        queuedTasks: res.queuedTasks,
        pendingApprovals: res.pendingApprovals || [],
      }
      tenantId.value = res.tenantId || tenantId.value
      post('status.updated', status.value)
    }
  } catch (e: any) {
    // A failed strip refresh is not worth breaking the host's page over.
    post('status.error', { reason: e?.data?.reason || e?.message || 'status unavailable' })
  }
}

async function submit(correlationId?: string) {
  const text = outcome.value.trim()
  if (!text || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    const res = await $fetch<any>('/api/embed/submit', {
      method: 'POST',
      headers: headers(),
      body: { outcome: text, hostApp: String(route.query.app ?? 'unknown') },
    })
    lastQueueId.value = res?.queueId || ''
    outcome.value = ''
    post('outcome.accepted', { queueId: lastQueueId.value }, correlationId)
    await refreshStatus()
  } catch (e: any) {
    error.value = e?.data?.reason || e?.message || 'submission failed'
    post('outcome.rejected', { reason: error.value }, correlationId)
  } finally {
    submitting.value = false
  }
}

function onHostMessage(event: MessageEvent) {
  // Rule 2: wrong origin, no conversation. Checked before parsing, so a hostile
  // page cannot even probe our envelope validation.
  if (!hostOrigin.value || event.origin !== hostOrigin.value) return
  const parsed = parseEnvelope(event.data)
  if (!parsed.ok) {
    post('envelope.rejected', { reason: parsed.reason })
    return
  }
  const env = parsed.envelope
  if (env.direction !== 'host_to_embed') return

  switch (env.kind) {
    case 'auth.key': {
      const key = (env.payload as any)?.key
      if (typeof key === 'string' && key) {
        embedKey.value = key
        tenantId.value = env.tenantId
        refreshStatus()
        post('auth.ready', { protocol: EMBED_PROTOCOL_VERSION }, env.correlationId)
      } else {
        post('auth.rejected', { reason: 'key missing' }, env.correlationId)
      }
      break
    }
    case 'outcome.prefill':
      outcome.value = String((env.payload as any)?.outcome ?? '')
      break
    case 'outcome.submit':
      outcome.value = String((env.payload as any)?.outcome ?? outcome.value)
      submit(env.correlationId)
      break
    case 'status.refresh':
      refreshStatus()
      break
    default:
      post('kind.unsupported', { kind: env.kind }, env.correlationId)
  }
}

onMounted(() => {
  window.addEventListener('message', onHostMessage)
  // Announce readiness so the host knows when to send the key rather than
  // guessing with a timeout.
  post('embed.ready', { protocol: EMBED_PROTOCOL_VERSION, surface: surface.value })
})
onBeforeUnmount(() => window.removeEventListener('message', onHostMessage))
</script>

<template>
  <div class="madeus-embed">
    <p v-if="!hostOrigin" class="embed-error">
      This surface must be mounted with a <code>?host=</code> origin. Without one it cannot
      reply to anybody, which is deliberate.
    </p>

    <template v-else>
      <form class="outcome" @submit.prevent="submit()">
        <label class="sr-only" for="outcome">What should we accomplish?</label>
        <textarea
          id="outcome"
          v-model="outcome"
          rows="3"
          placeholder="What should we accomplish?"
          :disabled="!embedKey || submitting"
        />
        <button type="submit" :disabled="!embedKey || submitting || !outcome.trim()">
          {{ submitting ? 'Sending…' : 'Send to the fleet' }}
        </button>
      </form>

      <p v-if="error" class="embed-error" role="alert">{{ error }}</p>
      <p v-else-if="lastQueueId" class="embed-ok">Queued as {{ lastQueueId }}.</p>

      <div v-if="status" class="strip">
        <span>{{ status.runningTasks }} running</span>
        <span>{{ status.queuedTasks }} queued</span>
        <span>{{ status.pendingApprovals.length }} awaiting you</span>
      </div>

      <ul v-if="status?.pendingApprovals?.length" class="approvals">
        <li v-for="a in status.pendingApprovals" :key="a.id">{{ a.summary }}</li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.madeus-embed { font-family: system-ui, sans-serif; padding: 12px; }
.outcome { display: flex; flex-direction: column; gap: 8px; }
.outcome textarea { width: 100%; padding: 8px; border-radius: 8px; border: 1px solid #d4d4d8; }
.outcome button { align-self: flex-end; padding: 6px 14px; border-radius: 8px; border: 0; background: #111; color: #fff; }
.outcome button:disabled { opacity: 0.5; }
.strip { display: flex; gap: 16px; margin-top: 12px; font-size: 13px; color: #52525b; }
.approvals { margin: 8px 0 0; padding-left: 18px; font-size: 13px; }
.embed-error { color: #b91c1c; font-size: 13px; }
.embed-ok { color: #15803d; font-size: 13px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
</style>

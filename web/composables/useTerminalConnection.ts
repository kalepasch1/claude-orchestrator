import { ref, onUnmounted } from 'vue'

export function useTerminalConnection(slug: string) {
  const connectionStatus = ref<'disconnected' | 'connecting' | 'connected'>('disconnected')
  const uptime = ref(0)
  let ws: WebSocket | null = null
  let uptimeInterval: ReturnType<typeof setInterval> | null = null
  let reconnectTimeout: ReturnType<typeof setTimeout> | null = null
  const startTime = ref(0)

  const listeners: Array<(data: any) => void> = []

  function onMessage(handler: (data: any) => void) {
    listeners.push(handler)
  }

  function connect() {
    if (connectionStatus.value === 'connected') return
    connectionStatus.value = 'connecting'

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${proto}//${window.location.host}/api/terminal/ws?slug=${slug}`

    try {
      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        connectionStatus.value = 'connected'
        startTime.value = Date.now()
        uptimeInterval = setInterval(() => {
          uptime.value = Date.now() - startTime.value
        }, 1000)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          listeners.forEach(fn => fn(data))
        } catch {
          // non-JSON message, ignore
        }
      }

      ws.onclose = () => {
        connectionStatus.value = 'disconnected'
        cleanup()
        // Auto-reconnect after 5s
        reconnectTimeout = setTimeout(() => connect(), 5000)
      }

      ws.onerror = () => {
        connectionStatus.value = 'disconnected'
        cleanup()
      }
    } catch {
      connectionStatus.value = 'disconnected'
      // Fallback: polling mode if WebSocket unavailable
      startPolling()
    }
  }

  function disconnect() {
    ws?.close()
    cleanup()
    connectionStatus.value = 'disconnected'
  }

  async function sendCommand(cmd: string): Promise<string> {
    // Try WebSocket first
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'command', payload: cmd }))
      return `Sent: ${cmd}`
    }

    // Fallback to REST
    const res = await $fetch<{ result: string }>('/api/terminal/command', {
      method: 'POST',
      body: { slug, command: cmd }
    })
    return res.result
  }

  let pollInterval: ReturnType<typeof setInterval> | null = null

  function startPolling() {
    connectionStatus.value = 'connected'
    startTime.value = Date.now()
    uptimeInterval = setInterval(() => {
      uptime.value = Date.now() - startTime.value
    }, 1000)

    pollInterval = setInterval(async () => {
      try {
        const data = await $fetch('/api/terminal/poll', {
          params: { slug }
        })
        listeners.forEach(fn => fn(data))
      } catch {
        // Silently retry
      }
    }, 3000)
  }

  function cleanup() {
    if (uptimeInterval) clearInterval(uptimeInterval)
    if (reconnectTimeout) clearTimeout(reconnectTimeout)
    if (pollInterval) clearInterval(pollInterval)
    uptimeInterval = null
    reconnectTimeout = null
    pollInterval = null
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connectionStatus,
    uptime,
    connect,
    disconnect,
    sendCommand,
    onMessage
  }
}

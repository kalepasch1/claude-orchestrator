<script setup lang="ts">
// Portfolio health — one glance: runner uptime, per-app deploy state, RLS security, momentum, spend.
const { data, pending, refresh } = await useFetch('/api/portfolio-health')
const money = (n: any) => '$' + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })
const dc = (s: string) => s === 'READY' ? '#39a06b' : ['ERROR', 'CANCELED'].includes(s) ? '#f2618f' : '#f0b429'
const sc = (s: string) => s === 'ok' ? '#39a06b' : s === 'critical' ? '#f2618f' : '#f0b429'
</script>
<template>
  <div style="max-width:1080px;margin:0 auto;padding:24px;font-family:-apple-system,Segoe UI,Inter,sans-serif">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h1 style="margin:0;font-size:18px">Portfolio Health</h1>
      <button @click="refresh()" style="padding:8px 14px;border-radius:8px;border:1px solid #ddd;cursor:pointer">Reload</button>
    </div>
    <div v-if="pending">Loading…</div>
    <template v-else>
      <!-- runner status banner -->
      <div :style="{padding:'10px 14px',borderRadius:'10px',marginBottom:'16px',fontSize:'14px',
                    background: data.runner.up ? 'rgba(57,160,107,.12)' : 'rgba(242,97,143,.14)',
                    border: '1px solid ' + (data.runner.up ? '#39a06b' : '#f2618f')}">
        Runner: <b>{{ data.runner.up ? 'UP' : 'DOWN' }}</b>
        <span style="color:#888"> · last heartbeat {{ data.runner.seconds_since_heartbeat ?? '—' }}s ago</span>
        <span v-if="data.alerts.length" style="color:#f2618f"> · {{ data.alerts.length }} open alert(s)</span>
      </div>

      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead><tr style="text-align:left;color:#8a97ad;border-bottom:1px solid #eee">
          <th style="padding:8px">App</th><th>Deploy</th><th>RLS</th><th>Momentum</th><th>Tokens 30d</th><th>Mkt spend</th>
        </tr></thead>
        <tbody>
          <tr v-for="a in data.apps" :key="a.app" style="border-bottom:1px solid #f2f2f2">
            <td style="padding:8px"><b>{{ a.app }}</b></td>
            <td><span :style="{color:dc(a.deploy_state)}">{{ a.deploy_state }}</span>
                <span v-if="a.deploy_alarm" title="merged but not deployed"> ⚠️</span></td>
            <td><span :style="{color:sc(a.rls_status)}">{{ a.rls_status || '—' }}</span>
                <span v-if="a.rls_off" style="color:#888"> ({{ a.rls_off }}/{{ a.total_tables }})</span></td>
            <td>{{ a.momentum != null ? Number(a.momentum).toFixed(0) : '—' }} <span style="color:#888">{{ a.trend||'' }}</span></td>
            <td>{{ money(a.token_cost_30d) }}</td>
            <td>{{ money(a.marketing_spend) }}</td>
          </tr>
        </tbody>
      </table>
      <p style="color:#8a97ad;font-size:12px;margin-top:10px">Deploy ⚠️ = a merge landed without a matching green Vercel deploy. RLS "critical" = tables exposed to the anon key.</p>
    </template>
  </div>
</template>

<script setup lang="ts">
// Orchestrator oversight of the Growth OS — the control-plane view. Shows how marketing momentum,
// budget, and spend map to AI token usage + a suggested improvement-focus weight per app.
const { data, pending, refresh } = await useFetch('/api/growth-oversight')
const money = (n: any) => '$' + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })
</script>

<template>
  <div style="max-width:1000px;margin:0 auto;padding:24px;font-family:-apple-system,Segoe UI,Inter,sans-serif">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
      <div>
        <h1 style="margin:0;font-size:18px">Growth OS — Oversight</h1>
        <div style="color:#8a97ad;font-size:13px">Marketing momentum → budget → AI token spend → where to focus improvement.</div>
      </div>
      <button @click="refresh()" style="padding:8px 14px;border-radius:8px;border:1px solid #ddd;cursor:pointer">Reload</button>
    </div>

    <div v-if="pending">Loading…</div>
    <template v-else>
      <div style="margin-bottom:16px;color:#555;font-size:14px">
        Incremental value created (counterfactual): <b>{{ data?.counterfactualValue ?? '—' }}</b> conversions vs. baseline.
      </div>

      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead>
          <tr style="text-align:left;color:#8a97ad;border-bottom:1px solid #eee">
            <th style="padding:8px">App</th><th>Momentum</th><th>Mkt budget</th><th>Mkt spend</th>
            <th>Token cost 30d</th><th>Token/Mkt</th><th>Focus weight</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in data?.spendTokens" :key="r.app" style="border-bottom:1px solid #f2f2f2">
            <td style="padding:8px"><b>{{ r.display_name || r.app }}</b> <span style="color:#aaa;font-size:11px">{{ r.tier }}</span></td>
            <td>{{ Number(r.momentum).toFixed(0) }}</td>
            <td>{{ money(r.marketing_budget) }}</td>
            <td>{{ money(r.marketing_spend) }}</td>
            <td>{{ money(r.token_cost_30d) }}</td>
            <td :style="{color: r.token_to_marketing > 1 ? '#f2618f' : '#555'}">{{ r.token_to_marketing ?? '—' }}</td>
            <td>
              <div style="display:flex;align-items:center;gap:6px">
                <div style="height:6px;border-radius:4px;background:#5b8cff" :style="{width: (r.focus_weight*1.5)+'px'}"></div>
                {{ r.focus_weight }}%
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <p style="color:#8a97ad;font-size:12px;margin-top:12px">
        Focus weight = share of portfolio momentum → the recommended split of orchestrator improvement/token budget.
        A high Token/Mkt ratio flags an app burning AI spend without marketing traction (review focus).
      </p>

      <h2 style="font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:#8a97ad;margin-top:24px">Autonomy accuracy</h2>
      <div v-for="g in data?.governance" :key="g.surface" style="font-size:14px;padding:4px 0">
        {{ g.surface }}: <b>{{ (Number(g.accuracy)*100).toFixed(0) }}%</b> ({{ g.overridden }}/{{ g.auto_actions }} overridden)
      </div>

      <h2 style="font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:#8a97ad;margin-top:24px">Campaigns</h2>
      <div v-for="c in data?.campaigns" :key="c.name" style="font-size:14px;padding:2px 0">
        {{ c.name }} — {{ c.app }} · <span :style="{color: c.status==='active' ? '#39a06b':'#999'}">{{ c.status }}</span>
      </div>
    </template>
  </div>
</template>

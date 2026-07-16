<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const { data, refresh } = await useFetch('/api/mcp/status')

const generating = ref(false)
const genForm = ref({ appName: '', repoPath: '', pricingTier: 'standard' })
const showGenModal = ref(false)

async function toggleGroup(groupId: string, action: 'activate' | 'deactivate' | 'sync') {
  await $fetch('/api/mcp/activate', { method: 'POST', body: { groupId, action } })
  await refresh()
}

async function generateMcp() {
  generating.value = true
  try {
    await $fetch('/api/mcp/generate', { method: 'POST', body: genForm.value })
    showGenModal.value = false
    genForm.value = { appName: '', repoPath: '', pricingTier: 'standard' }
    await refresh()
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <div class="mcp-page" v-if="data">
    <header class="mcp-header">
      <div>
        <h1>MCP Distribution</h1>
        <p class="mcp-sub">Unified MCP server — {{ data.stats.totalTools }} tools across {{ data.stats.activeGroups }} groups</p>
      </div>
      <button class="btn-primary" @click="showGenModal = true">+ Generate MCP for New App</button>
    </header>

    <div class="mcp-stats">
      <div class="stat-card"><span class="stat-n">{{ data.stats.totalTools }}</span><span class="stat-l">Total Tools</span></div>
      <div class="stat-card"><span class="stat-n">{{ data.stats.activeGroups }}</span><span class="stat-l">Active Groups</span></div>
      <div class="stat-card"><span class="stat-n">{{ data.stats.totalListings }}</span><span class="stat-l">Marketplace Listings</span></div>
    </div>

    <section class="mcp-groups">
      <h2>Tool Groups</h2>
      <div class="group-grid">
        <div v-for="g in data.groups" :key="g.id" class="group-card" :class="{ disabled: !g.enabled }">
          <div class="group-top">
            <span class="group-icon">{{ g.icon }}</span>
            <div class="group-info">
              <h3>{{ g.label }}</h3>
              <span class="group-cat">{{ g.category }}</span>
            </div>
            <span class="group-count">{{ g.toolCount }} tools</span>
          </div>
          <p class="group-desc">{{ g.description }}</p>
          <div class="group-pricing">
            <span v-for="p in g.pricingSummary" :key="p" class="price-tag">{{ p }}</span>
          </div>
          <div class="group-actions">
            <button v-if="g.enabled" class="btn-sm btn-outline" @click="toggleGroup(g.id, 'deactivate')">Deactivate</button>
            <button v-else class="btn-sm btn-primary" @click="toggleGroup(g.id, 'activate')">Activate</button>
            <button class="btn-sm btn-outline" @click="toggleGroup(g.id, 'sync')">Sync</button>
          </div>
        </div>
      </div>
    </section>

    <section class="mcp-listings">
      <h2>Marketplace Listings</h2>
      <div class="listing-grid">
        <div v-for="l in data.listings" :key="l.id" class="listing-card">
          <span class="listing-icon">{{ l.icon }}</span>
          <div>
            <h4>{{ l.displayName }}</h4>
            <p>{{ l.tagline }}</p>
            <span class="listing-tier">{{ l.pricingTier }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="mcp-sync-info">
      <h2>Live Sync</h2>
      <p>MCP tools auto-update when source apps push to <code>main</code>. Core apps log new capabilities for manual review; non-core apps fully regenerate.</p>
      <p>Webhook: <code>POST /api/webhooks/mcp-sync</code></p>
    </section>

    <Teleport to="body">
      <div v-if="showGenModal" class="modal-backdrop" @click.self="showGenModal = false">
        <div class="modal-box">
          <h3>Generate MCP for New App</h3>
          <label>App Name<input v-model="genForm.appName" placeholder="my-new-app" /></label>
          <label>Repo Path<input v-model="genForm.repoPath" placeholder="/path/to/repo" /></label>
          <label>Pricing Tier
            <select v-model="genForm.pricingTier">
              <option value="budget">Budget</option>
              <option value="standard">Standard</option>
              <option value="premium">Premium</option>
            </select>
          </label>
          <div class="modal-actions">
            <button class="btn-sm btn-outline" @click="showGenModal = false">Cancel</button>
            <button class="btn-sm btn-primary" :disabled="generating || !genForm.appName" @click="generateMcp">
              {{ generating ? 'Generating...' : 'Generate' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.mcp-page{padding:32px 40px 80px;max-width:1200px}
.mcp-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:28px}
.mcp-header h1{font:600 22px/1.2 Inter,system-ui,sans-serif;color:#111;margin:0}
.mcp-sub{color:#888;font-size:11px;margin-top:4px}
.btn-primary{background:#111;color:#fff;border:0;border-radius:8px;padding:9px 16px;font-size:11px;cursor:pointer;font-weight:600;transition:.15s}
.btn-primary:hover{background:#333}
.btn-primary:disabled{opacity:.4;cursor:default}
.btn-sm{padding:6px 12px;font-size:10px;border-radius:6px;cursor:pointer;font-weight:600}
.btn-outline{background:transparent;border:1px solid #ddd;color:#555}
.btn-outline:hover{border-color:#999;color:#111}
.mcp-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:32px}
.stat-card{background:#fff;border:1px solid #e5e5e0;border-radius:10px;padding:18px 20px;display:flex;flex-direction:column;gap:4px}
.stat-n{font:700 28px/1 JetBrains Mono,monospace;color:#111}
.stat-l{font-size:10px;color:#999;text-transform:uppercase;letter-spacing:.08em}
.mcp-groups h2,.mcp-listings h2,.mcp-sync-info h2{font:600 14px/1.3 Inter,system-ui,sans-serif;margin:0 0 14px;text-transform:uppercase;letter-spacing:.06em;font-size:10px;color:#999}
.group-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;margin-bottom:32px}
.group-card{background:#fff;border:1px solid #e5e5e0;border-radius:10px;padding:18px 20px;transition:.15s}
.group-card.disabled{opacity:.5}
.group-top{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.group-icon{font-size:20px;width:36px;height:36px;display:flex;align-items:center;justify-content:center;background:#f5f5f2;border-radius:8px}
.group-info{flex:1}
.group-info h3{font:600 13px/1.3 Inter,system-ui,sans-serif;color:#111;margin:0}
.group-cat{font-size:9px;color:#999}
.group-count{font:600 10px JetBrains Mono,monospace;color:#666;background:#f5f5f2;padding:3px 8px;border-radius:4px}
.group-desc{font-size:11px;color:#666;margin:0 0 10px;line-height:1.5}
.group-pricing{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}
.price-tag{font:500 9px JetBrains Mono,monospace;background:#f0f8f0;color:#2a7a2a;padding:2px 7px;border-radius:4px}
.group-actions{display:flex;gap:6px}
.listing-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin-bottom:32px}
.listing-card{background:#fff;border:1px solid #e5e5e0;border-radius:10px;padding:16px 18px;display:flex;gap:12px;align-items:flex-start}
.listing-icon{font-size:22px;width:40px;height:40px;display:flex;align-items:center;justify-content:center;background:#f5f5f2;border-radius:8px;flex-shrink:0}
.listing-card h4{font:600 12px/1.3 Inter,system-ui,sans-serif;color:#111;margin:0 0 3px}
.listing-card p{font-size:10px;color:#888;margin:0 0 6px;line-height:1.4}
.listing-tier{font:600 8px JetBrains Mono,monospace;color:#555;background:#f5f5f2;padding:2px 6px;border-radius:3px;text-transform:uppercase}
.mcp-sync-info{background:#fff;border:1px solid #e5e5e0;border-radius:10px;padding:20px 22px;margin-bottom:32px}
.mcp-sync-info p{font-size:11px;color:#666;line-height:1.6;margin:0 0 6px}
.mcp-sync-info code{font:11px JetBrains Mono,monospace;background:#f5f5f2;padding:2px 6px;border-radius:3px}
.modal-backdrop{position:fixed;inset:0;background:#0005;display:flex;align-items:center;justify-content:center;z-index:100}
.modal-box{background:#fff;border-radius:12px;padding:28px 30px;width:420px;box-shadow:0 20px 60px #0003}
.modal-box h3{font:600 16px/1.3 Inter,system-ui,sans-serif;margin:0 0 18px}
.modal-box label{display:block;font-size:10px;color:#888;margin-bottom:12px;text-transform:uppercase;letter-spacing:.06em}
.modal-box input,.modal-box select{display:block;width:100%;margin-top:4px;padding:8px 10px;border:1px solid #ddd;border-radius:6px;font-size:12px;box-sizing:border-box}
.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}
</style>

<script setup lang="ts">
const route = useRoute()
const open = ref(false)
const sections = [
  { label: 'Command', items: [['Overview','/admin','◉'],['Terminal','/admin/terminal','⌬'],['Events','/admin/events','⌁'],['Chat','/admin/chat','↗'],['Playbooks','/admin/playbooks','▷']] },
  { label: 'Intelligence', items: [['Predictions','/admin/predictions','◌'],['Knowledge graph','/admin/knowledge-graph','⌘'],['Anomalies','/admin/anomalies','△'],['Shadow decisions','/admin/shadow','◐']] },
  { label: 'Assurance', items: [['Capability passport','/admin/capability-passport','◇'],['Compliance','/admin/compliance','✓'],['Regulatory','/admin/regulatory','§'],['Policies','/admin/policies','≡'],['Gateway','/admin/gateway','↔']] },
  { label: 'Operations', items: [['Deploys','/admin/deploys','↑'],['Telemetry','/admin/telemetry','∿'],['Costs','/admin/costs','$'],['Revenue','/admin/revenue','↗'],['Prompt ops','/admin/prompt-ops','✦'],['Temporal','/admin/temporal','↶'],['Replay','/admin/replay','▶'],['Sessions','/admin/session-replay','◎'],['Chaos lab','/admin/chaos','⚡']] },
]
function active(path: string) { return path === '/admin' ? route.path === path : route.path.startsWith(path) }
</script>

<template>
  <div class="admin-shell">
    <button v-if="open" class="admin-scrim" aria-label="Close navigation" @click="open=false" />
    <aside :class="{ open }">
      <header><NuxtLink to="/"><MadeusLogo /></NuxtLink><span>ADMIN CONTROL</span></header>
      <div class="admin-health"><i /> All control systems nominal <b>LIVE</b></div>
      <nav>
        <section v-for="section in sections" :key="section.label">
          <p>{{ section.label }}</p>
          <NuxtLink v-for="item in section.items" :key="item[1]" :to="item[1]" :class="{ active: active(item[1]) }" @click="open=false"><i>{{ item[2] }}</i><span>{{ item[0] }}</span><b>→</b></NuxtLink>
        </section>
      </nav>
      <footer><NuxtLink to="/">← Return to workspace</NuxtLink><small>Madeus assurance plane</small></footer>
    </aside>
    <div class="admin-stage">
      <header class="admin-mobile"><button @click="open=true">☰</button><MadeusLogo compact /><span>Admin</span></header>
      <main><slot /></main>
    </div>
  </div>
</template>

<style scoped>
.admin-shell{--admin-ink:#0a1020;--admin-line:#dce4ef;display:flex;height:100vh;overflow:hidden;background:#f5f8fc;color:var(--admin-ink)}aside{display:flex;width:248px;flex:0 0 auto;flex-direction:column;border-right:1px solid var(--admin-line);background:#f8fbff;box-shadow:16px 0 54px #1c355b0f}aside>header{display:flex;height:73px;align-items:center;justify-content:space-between;padding:0 18px;border-bottom:1px solid var(--admin-line)}aside>header a{color:#0a1020;text-decoration:none}aside>header>span{color:#7f8da2;font:650 7px JetBrains Mono,monospace;letter-spacing:.12em}.admin-health{display:flex;align-items:center;gap:7px;margin:12px;padding:10px;border:1px solid #d7e6f6;border-radius:9px;background:#eef6ff;color:#42658e;font-size:8px}.admin-health i{width:6px;height:6px;border-radius:50%;background:#17a66b;box-shadow:0 0 0 4px #17a66b18}.admin-health b{margin-left:auto;color:#168357;font:650 6px JetBrains Mono,monospace}nav{flex:1;overflow:auto;padding:0 10px 18px}nav section{margin-top:14px}nav p{margin:0 10px 6px;color:#96a2b4;font:700 7px JetBrains Mono,monospace;letter-spacing:.13em;text-transform:uppercase}nav a{display:grid;grid-template-columns:20px 1fr auto;gap:7px;align-items:center;border:1px solid transparent;border-radius:8px;padding:8px 10px;color:#59677d;text-decoration:none;font-size:10px;transition:.16s}nav a:hover{border-color:#d8e4f7;background:#f0f6ff;color:#14203a}nav a.active{border-color:#d6e3fa;background:#eaf2ff;color:#153e90;box-shadow:inset 3px 0 #2563eb,0 5px 14px #2563eb12}nav a i{color:#5274a8;font-style:normal;text-align:center}nav a b{opacity:0;font-weight:400}nav a.active b{opacity:.8}aside footer{display:flex;flex-direction:column;gap:5px;padding:15px 18px;border-top:1px solid var(--admin-line)}aside footer a{color:#425b7d;text-decoration:none;font-size:9px}aside footer small{color:#94a0b2;font-size:7px}.admin-stage{display:flex;min-width:0;flex:1;flex-direction:column}.admin-stage>main{flex:1;overflow:auto;background:radial-gradient(circle at 85% 0,#e2efff,transparent 27%),#f5f8fc}.admin-mobile{display:none}.admin-scrim{display:none}@media(max-width:820px){aside{position:fixed;z-index:80;inset:0 auto 0 0;transform:translateX(-100%);transition:transform .22s}aside.open{transform:translateX(0)}.admin-scrim{position:fixed;z-index:70;inset:0;display:block;border:0;background:#0006;backdrop-filter:blur(4px)}.admin-mobile{display:flex;height:54px;align-items:center;gap:11px;padding:0 15px;border-bottom:1px solid var(--admin-line);background:#f8fbff}.admin-mobile button{border:0;background:transparent}.admin-mobile>span{margin-left:auto;color:#6b7890;font-size:9px}}
</style>

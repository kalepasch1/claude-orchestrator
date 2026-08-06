<script setup lang="ts">
definePageMeta({ layout: false })
const route = useRoute()
const { data, error, status } = await useFetch<any>(`/api/public/proof/${encodeURIComponent(String(route.params.token || ''))}`)
const copied = ref(false)
async function copyDigest() {
  if (!data.value?.proof?.proof_digest || !import.meta.client) return
  await navigator.clipboard.writeText(data.value.proof.proof_digest)
  copied.value = true
  setTimeout(() => { copied.value = false }, 1600)
}
function readable(value: unknown) { return String(value || 'Not recorded').replaceAll('_', ' ') }
</script>

<template>
  <main class="proof-page">
    <nav><NuxtLink to="/" aria-label="Madeus home"><MadeusLogo /></NuxtLink><span>Scoped proof portal</span></nav>
    <section v-if="status === 'pending'" class="state"><i /> Verifying evidence envelope…</section>
    <section v-else-if="error" class="state invalid"><b>Proof link unavailable</b><p>This reviewer link is invalid, expired, or revoked. Request a fresh scoped link from the Madeus operator.</p></section>
    <article v-else class="proof-card">
      <header><div><span class="eyebrow">Verified execution evidence</span><h1>{{ readable(data.proof.intent || data.proof.action_type) }}</h1><p>This read-only view shares the decision proof required for review without exposing internal access, prompts, connector secrets, or raw user records.</p></div><div class="seal"><i>✓</i><b>{{ data.verification.digest_present ? 'Digest present' : 'Evidence pending' }}</b><small>Unrevoked at load</small></div></header>
      <div class="facts"><div><span>Status</span><b>{{ readable(data.proof.status) }}</b></div><div><span>Audience</span><b>{{ data.audience }}</b></div><div><span>Created</span><b>{{ new Date(data.proof.created_at).toLocaleString() }}</b></div><div><span>Access expires</span><b>{{ new Date(data.expires_at).toLocaleString() }}</b></div></div>
      <section><span class="eyebrow">Prediction and constraints</span><div class="evidence-grid"><pre>{{ JSON.stringify(data.proof.prediction || {}, null, 2) }}</pre><pre>{{ JSON.stringify(data.proof.rollback_plan || {}, null, 2) }}</pre></div></section>
      <section class="digest"><div><span class="eyebrow">Tamper-evident digest</span><code>{{ data.proof.proof_digest || 'No digest recorded' }}</code></div><button :disabled="!data.proof.proof_digest" @click="copyDigest">{{ copied ? 'Copied ✓' : 'Copy digest' }}</button></section>
      <footer><span>Read-only</span><span>Least-privilege scope</span><span>No connector credentials</span><span>No raw interaction records</span></footer>
    </article>
  </main>
</template>

<style scoped>
.proof-page{min-height:100vh;background:#f5f7f4;color:#171b18;font-family:Inter,ui-sans-serif,system-ui,sans-serif;padding:28px}.proof-page>nav{display:flex;max-width:1040px;margin:auto;align-items:center;justify-content:space-between;color:#607067;font-size:11px;font-weight:650;text-transform:uppercase;letter-spacing:.12em}.proof-page>nav a{width:110px;color:#143f2e}.proof-card,.state{max-width:1040px;margin:54px auto 0;border:1px solid #d7dfd9;border-radius:22px;background:#fff;box-shadow:0 18px 60px rgba(18,52,37,.06)}.state{padding:48px;text-align:center}.state i{display:inline-block;width:9px;height:9px;margin-right:8px;border-radius:50%;background:#237b4e;box-shadow:0 0 0 5px #dfeee5}.state.invalid b{display:block;font-size:22px}.state.invalid p{margin:8px auto 0;max-width:480px;color:#67736b;font-size:13px}.proof-card{overflow:hidden}.proof-card>header{display:flex;justify-content:space-between;gap:32px;padding:44px}.eyebrow{display:block;color:#184c35;font-size:10px;font-weight:750;text-transform:uppercase;letter-spacing:.15em}.proof-card h1{max-width:700px;margin:10px 0 0;font-size:34px;line-height:1.12;letter-spacing:-.045em}.proof-card header p{max-width:680px;margin-top:13px;color:#667169;font-size:13px;line-height:1.65}.seal{display:flex;min-width:150px;align-self:flex-start;flex-direction:column;align-items:center;border:1px solid #d6e4da;border-radius:16px;background:#f2f8f4;padding:18px;text-align:center}.seal i{display:grid;width:32px;height:32px;place-items:center;border-radius:50%;background:#184c35;color:#fff;font-style:normal}.seal b{margin-top:9px;font-size:11px}.seal small{margin-top:2px;color:#77827a;font-size:9px}.facts{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid #e0e5e1;border-bottom:1px solid #e0e5e1;background:#fafbf9}.facts div{padding:18px 22px;border-right:1px solid #e0e5e1}.facts div:last-child{border:0}.facts span,.facts b{display:block}.facts span{color:#849087;font-size:9px}.facts b{margin-top:6px;font-size:11px;text-transform:capitalize}.proof-card>section{padding:28px 44px}.evidence-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.evidence-grid pre{overflow:auto;min-height:130px;margin:0;border:1px solid #e0e5e1;border-radius:12px;background:#fafbf9;padding:16px;color:#455149;font:10px/1.6 ui-monospace,SFMono-Regular,monospace}.digest{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;border-top:1px solid #e0e5e1}.digest code{display:block;overflow-wrap:anywhere;margin-top:10px;color:#354139;font-size:10px}.digest button{flex:none;border:0;border-radius:9px;background:#184c35;padding:10px 13px;color:white;font-size:10px;font-weight:650}.proof-card>footer{display:flex;gap:20px;border-top:1px solid #e0e5e1;background:#f6f8f5;padding:16px 44px;color:#768078;font-size:9px}.proof-card>footer span:before{content:'✓';margin-right:5px;color:#237b4e}@media(max-width:720px){.proof-page{padding:18px}.proof-card{margin-top:28px}.proof-card>header{flex-direction:column;padding:28px}.proof-card h1{font-size:26px}.seal{width:100%}.facts{grid-template-columns:1fr 1fr}.facts div:nth-child(2){border-right:0}.proof-card>section{padding:24px 28px}.evidence-grid{grid-template-columns:1fr}.digest{align-items:stretch;flex-direction:column}.proof-card>footer{flex-direction:column;gap:6px;padding:16px 28px}}
</style>

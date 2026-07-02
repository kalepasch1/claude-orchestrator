#!/usr/bin/env node
/**
 * Corpus-fed content/SEO engine — demand-driven authority content, on autopilot.
 *
 * WHY THIS IS 20-500X: Apparently and Tomorrow already run a legal/regulatory corpus with a
 * query-log GAP DETECTOR (corpus_gaps) that literally records what authoritative content is in
 * DEMAND but MISSING. This engine turns that demand signal into published, citation-backed pages
 * that competitors can't reproduce (they don't have the corpus). It closes the loop:
 *
 *   corpus gap (demand)  ->  growth_content row  ->  gtm task (swarm drafts w/ corpus citations)
 *      ->  cite-check against corpus  ->  human review (approval)  ->  publish
 *      ->  repurpose (newsletter/social/landing)  ->  emit content_published event
 *      ->  momentum + the SAME corpus query log measures whether it answered real demand.
 *
 * This script is the ORCHESTRATION step: it reads gaps from an app's corpus DB and seeds the
 * pipeline (content rows + gtm tasks) in the orchestrator DB. The swarm (runner) does the drafting,
 * cite-checking and repurposing as normal gtm tasks; a human approves before publish via Smarter.
 *
 * Env:
 *   ORCH_SUPABASE_URL / ORCH_SUPABASE_SERVICE_KEY   (orchestrator control-plane DB)
 *   APP_SUPABASE_URL  / APP_SUPABASE_SERVICE_KEY     (the product's DB, e.g. apparently/tomorrow)
 *   APP_NAME=apparently   TOP_N=10
 */
import { createClient } from '@supabase/supabase-js'

const APP = process.env.APP_NAME || 'apparently'
const TOP_N = Number(process.env.TOP_N || 10)

const orch = createClient(process.env.ORCH_SUPABASE_URL, process.env.ORCH_SUPABASE_SERVICE_KEY)
const app = createClient(process.env.APP_SUPABASE_URL, process.env.APP_SUPABASE_SERVICE_KEY)

// 1) Pull top DEMAND gaps from the app corpus. corpus_gaps is auto-populated by log_corpus_query()
//    whenever a query returns weak/no authority — i.e. real demand the corpus can't yet answer.
async function topGaps() {
  const { data, error } = await app
    .from('corpus_gaps')
    .select('id, query, hits, top_rank, created_at')
    .order('hits', { ascending: false })
    .limit(TOP_N)
  if (error) throw new Error(`corpus_gaps read failed: ${error.message}`)
  return data || []
}

// 2) For each gap, find the best available supporting authority so the draft is grounded.
async function supportingRefs(query) {
  // search_corpus_authority is the app's usage-boosted FTS/semantic search RPC.
  const { data } = await app.rpc('search_corpus_authority', { q: query, k: 6 }).catch(() => ({ data: [] }))
  return (data || []).map(d => ({ id: d.id ?? d.doc_id, title: d.title, cite: d.citation ?? null }))
}

// 3) Seed a content row + a gtm task in the orchestrator. Keep slugs STABLE (optimization key).
async function seed(gap, refs) {
  const slug = `content-${APP}-${gap.id}`
  const primary_keyword = gap.query

  const { data: content, error: cErr } = await orch
    .from('growth_content')
    .upsert({
      app: APP,
      topic: gap.query,
      primary_keyword,
      gap_demand: gap.hits ?? 0,
      corpus_refs: refs,
      status: 'drafting',
      meta: { corpus_gap_id: gap.id, top_rank: gap.top_rank },
    }, { onConflict: 'app,primary_keyword' })
    .select()
    .maybeSingle()
  if (cErr) console.warn(`content upsert warn (${slug}): ${cErr.message}`)

  const prompt = [
    `Write an authoritative, citation-backed expertise article for ${APP} on: "${gap.query}".`,
    `Audience: the ICP for ${APP}. Goal: rank for "${primary_keyword}" AND convert demand this exact query represents.`,
    `GROUND every claim in the supplied corpus authorities and cite them inline. Do NOT invent citations.`,
    `Supporting authorities (corpus doc ids): ${JSON.stringify(refs)}`,
    `Then produce derivatives: (a) 150-word newsletter blurb, (b) 3 social posts, (c) landing-page hero + 3 bullets.`,
    `Acceptance: cite-check passes (every legal/factual claim maps to a corpus doc), reading level appropriate,`,
    `primary keyword in H1+first paragraph, and a clear CTA into the relevant ${APP} product.`,
    `On completion set growth_content.status='review' and file an approval (kind='gtm') for human sign-off.`,
  ].join('\n')

  const { error: tErr } = await orch.from('tasks').insert({
    project: APP,           // resolved to project by the runner; also stored on outcomes
    slug,
    prompt,
    kind: 'gtm',
    state: 'QUEUED',
    note: `content-engine: demand=${gap.hits} gap#${gap.id}`,
  })
  if (tErr) console.warn(`task insert warn (${slug}): ${tErr.message}`)
  return { slug, content_id: content?.id, demand: gap.hits }
}

async function main() {
  const gaps = await topGaps()
  if (!gaps.length) { console.log(`No demand gaps for ${APP}. Corpus is answering what's asked.`); return }
  const out = []
  for (const g of gaps) {
    const refs = await supportingRefs(g.query)
    out.push(await seed(g, refs))
  }
  console.table(out)
  console.log(`Seeded ${out.length} corpus-fed content tasks for ${APP}. Swarm will draft; you approve in Smarter.`)
}

main().catch(e => { console.error(e); process.exit(1) })
